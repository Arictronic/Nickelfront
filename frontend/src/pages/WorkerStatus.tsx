import { useEffect, useRef, useState } from "react";
import {
  getPapersCount,
  getCeleryTaskStatus,
  revokeCeleryTask,
  deleteCeleryTask,
  getSharedParseJobs,
  deleteSharedParseJob,
  type CeleryTaskStatus,
} from "../api/papers";
import type { PaperSource } from "../types/paper";

type ParseJob = {
  jobId: string;
  startedAt: number;
  query: string;
  source: PaperSource | "all";
  initialCount: number;
  lastObservedCount: number;
  lastCountChangeAt: number;
  status: "in_progress" | "completed" | "cancelled" | "failed" | "expired";
  celeryStatus?: CeleryTaskStatus;
  lastPolledAt?: number;
};

const LS_KEY = "parseJobs";
const LEGACY_LS_KEYS = ["parseJobs.v6", "parseJobs.v5", "parseJobs.v4", "parseJobs.v3", "parseJobs.v2", "parseJobs.v1", "parseJobs.reset.v3"];
const STALE_PENDING_TASK_MS = 30 * 60_000;

function clearLegacyParseJobKeys() {
  for (const key of LEGACY_LS_KEYS) {
    localStorage.removeItem(key);
  }
}

function clearParseJobStorage() {
  clearLegacyParseJobKeys();
  localStorage.removeItem(LS_KEY);
}

function isValidParseJob(job: unknown): job is ParseJob {
  const maybeJob = job as Partial<ParseJob> | null | undefined;
  return typeof maybeJob?.jobId === "string" && maybeJob.jobId.trim().length > 0;
}

function normalizeJobs(jobs: unknown): ParseJob[] {
  if (!Array.isArray(jobs)) return [];
  return jobs
    .filter(isValidParseJob)
    .map((job) => ({
      ...job,
      jobId: String(job.jobId),
      source: job.source as PaperSource | "all",
      status: (["in_progress", "completed", "cancelled", "failed", "expired"].includes(String(job.status))
        ? job.status
        : "in_progress") as ParseJob["status"],
    }));
}

function isExpiredPendingTask(job: ParseJob, now: number): boolean {
  return job.status === "in_progress" && now - job.lastCountChangeAt > STALE_PENDING_TASK_MS && job.lastObservedCount <= job.initialCount;
}

function loadJobs(): ParseJob[] {
  try {
    // Старые версионные ключи не используем: после runtime-cleanup они могут
    // содержать task_id, которых уже нет в Redis/Celery.
    clearLegacyParseJobKeys();
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    return normalizeJobs(JSON.parse(raw));
  } catch {
    clearParseJobStorage();
    return [];
  }
}

function saveJobs(jobs: ParseJob[]) {
  localStorage.setItem(LS_KEY, JSON.stringify(normalizeJobs(jobs)));
}

function mergeJobs(localJobs: ParseJob[], sharedJobs: ParseJob[]): ParseJob[] {
  const byId = new Map<string, ParseJob>();
  for (const job of normalizeJobs(localJobs)) {
    byId.set(job.jobId, job);
  }
  // Backend/shared history is fresher than browser localStorage.
  for (const job of normalizeJobs(sharedJobs)) {
    byId.set(job.jobId, job);
  }
  return Array.from(byId.values()).sort((a, b) => b.startedAt - a.startedAt).slice(0, 50);
}

export default function WorkerStatus() {
  const [jobs, setJobs] = useState<ParseJob[]>(() => loadJobs());
  const [allCount, setAllCount] = useState<number>(0);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number>(Date.now());
  const [error, setError] = useState<string | null>(null);
  const jobsRef = useRef<ParseJob[]>(jobs);
  const pollingRef = useRef(false);

  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  useEffect(() => {
    let cancelled = false;

    Promise.all([getPapersCount("all"), getSharedParseJobs(50)])
      .then(([count, sharedJobsRaw]) => {
        if (cancelled) return;

        const sharedJobs = normalizeJobs(sharedJobsRaw);
        setAllCount(count);

        // После runtime cleanup backend удаляет data/parse_jobs.json и papers.
        // В этом состоянии локальная browser-история устарела: не надо опрашивать
        // старые task_id и создавать видимость "живых" задач.
        if (count === 0 && sharedJobs.length === 0) {
          clearParseJobStorage();
          jobsRef.current = [];
          setJobs([]);
          return;
        }

        setJobs((current) => {
          const merged = mergeJobs(current, sharedJobs);
          jobsRef.current = merged;
          saveJobs(merged);
          return merged;
        });
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const refreshJobs = async (baseJobs?: ParseJob[]) => {
    const sourceJobs = baseJobs ?? jobsRef.current;
    if (sourceJobs.length === 0) {
      const total = await getPapersCount("all");
      setAllCount(total);
      setLastUpdatedAt(Date.now());
      return;
    }

    const updatedJobs = await Promise.all(
      sourceJobs.map(async (job) => {
        if (job.status !== "in_progress") return job;
        if (job.celeryStatus?.status === "REVOKED") return job;

        try {
          const celeryStatus = await getCeleryTaskStatus(job.jobId);
          const now = Date.now();
          const isSuccess = celeryStatus.status === "SUCCESS";
          const isFailure = celeryStatus.status === "FAILURE";
          const isCompleted = isSuccess || isFailure;
          const isRevoked = celeryStatus.status === "REVOKED";
          const savedCount = celeryStatus.saved_count || celeryStatus.total_saved || celeryStatus.result?.saved_count || celeryStatus.result?.total_saved || 0;

          if (celeryStatus.status === "PENDING") {
            const source = job.source === "all" ? "all" : job.source;
            const current = await getPapersCount(source as any);
            const changed = current !== job.lastObservedCount;
            const lastCountChangeAt = changed ? now : job.lastCountChangeAt;
            const stableMs = 60_000;
            const shouldComplete = now - lastCountChangeAt > stableMs && current > job.initialCount;
            const expired = !shouldComplete && isExpiredPendingTask({ ...job, lastObservedCount: current, lastCountChangeAt }, now);

            return {
              ...job,
              celeryStatus,
              lastObservedCount: current,
              lastCountChangeAt,
              lastPolledAt: now,
              status: shouldComplete ? "completed" : expired ? "expired" : "in_progress",
            } as ParseJob;
          }

          return {
            ...job,
            celeryStatus,
            lastObservedCount: savedCount > 0 ? savedCount : job.lastObservedCount,
            lastCountChangeAt: isCompleted ? now : job.lastCountChangeAt,
            lastPolledAt: now,
            status: isRevoked ? "cancelled" : isFailure ? "failed" : isSuccess ? "completed" : "in_progress",
          } as ParseJob;
        } catch {
          const source = job.source === "all" ? "all" : job.source;
          const current = await getPapersCount(source as any);
          const now = Date.now();
          const changed = current !== job.lastObservedCount;

          const next: ParseJob = {
            ...job,
            lastObservedCount: current,
            lastCountChangeAt: changed ? now : job.lastCountChangeAt,
          };

          const stableMs = 60_000;
          if (now - next.lastCountChangeAt > stableMs && current > next.initialCount) {
            next.status = "completed";
          } else if (isExpiredPendingTask(next, now)) {
            next.status = "expired";
          }
          return next;
        }
      })
    );

    // If user clicked "clear history" while refresh was in-flight, keep list empty.
    if (jobsRef.current.length === 0) {
      const total = await getPapersCount("all");
      setAllCount(total);
      setLastUpdatedAt(Date.now());
      return;
    }

    setJobs(updatedJobs);
    jobsRef.current = updatedJobs;
    saveJobs(updatedJobs);

    const total = await getPapersCount("all");
    setAllCount(total);
    setLastUpdatedAt(Date.now());
  };

  // Polling статуса задач Celery
  useEffect(() => {
    if (!jobsRef.current.some((job) => job.status === "in_progress")) return;
    let cancelled = false;

    const pollInterval = window.setInterval(async () => {
      if (cancelled || pollingRef.current || !jobsRef.current.some((job) => job.status === "in_progress")) return;
      pollingRef.current = true;
      try {
        await refreshJobs();
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        pollingRef.current = false;
      }
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(pollInterval);
    };
  }, [jobs.length]);

  const inProgress = jobs.filter((j) => j.status === "in_progress").length;
  const completed = jobs.filter((j) => j.status === "completed").length;

  const clearHistory = async () => {
    if (!window.confirm("Очистить историю задач? Записи будут удалены из интерфейса и общей истории backend. Celery-задачи не перезапускаются.")) return;
    const knownJobs = jobsRef.current;
    setError(null);
    await Promise.allSettled(knownJobs.map((job) => deleteSharedParseJob(job.jobId)));
    jobsRef.current = [];
    setJobs([]);
    clearParseJobStorage();
    setLastUpdatedAt(Date.now());
  };

  const cancelJob = async (jobId: string) => {
    if (!window.confirm("Остановить задачу? В очереди она будет отменена, а запущенная может не прерваться сразу.")) {
      return;
    }

    try {
      await revokeCeleryTask(jobId, false);
      const nextJobs: ParseJob[] = jobs.map((job): ParseJob =>
        job.jobId === jobId
          ? {
              ...job,
              status: "cancelled",
              celeryStatus: {
                ...(job.celeryStatus || {}),
                task_id: job.jobId,
                status: "REVOKED",
                state: "REVOKED",
              },
            }
          : job
      );
      setJobs(nextJobs);
      jobsRef.current = nextJobs;
      saveJobs(nextJobs);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const deleteJob = async (jobId: string) => {
    if (!window.confirm("Удалить задачу из истории? Это не повлияет на Celery, только удалит запись из интерфейса.")) {
      return;
    }

    try {
      await Promise.allSettled([deleteCeleryTask(jobId), deleteSharedParseJob(jobId)]);
      const nextJobs: ParseJob[] = jobs.filter((job) => job.jobId !== jobId);
      setJobs(nextJobs);
      jobsRef.current = nextJobs;
      saveJobs(nextJobs);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const getProgressPercent = (job: ParseJob): number => {
    if (job.status === "completed") return 100;
    if (job.status === "failed" || job.status === "expired") return 0;
    if (job.celeryStatus) {
      const current = job.celeryStatus.current || job.celeryStatus.result?.current || 0;
      const total = job.celeryStatus.total || job.celeryStatus.result?.total || 0;
      if (total > 0) return Math.round((current / total) * 100);
    }
    const delta = job.lastObservedCount - job.initialCount;
    const expectedDelta = 50;
    return Math.min(100, Math.round((delta / expectedDelta) * 100));
  };

  const getStatusText = (job: ParseJob): string => {
    if (job.status === "completed") return "✓ Завершено";
    if (job.status === "failed") return "✕ Ошибка";
    if (job.status === "cancelled") return "Отменено";
    if (job.status === "expired") return "Истёк / не найден";

    if (job.celeryStatus) {
      const status = job.celeryStatus.status;
      const stateText = job.celeryStatus.result?.status || job.celeryStatus.state || "";

      if (status === "SUCCESS") return "✓ Завершено";
      if (status === "FAILURE") return "✗ Ошибка";
      if (status === "REVOKED") return "Отменено";
      if (status === "PENDING") return "Ожидание...";
      if (status === "STARTED") return stateText || "В процессе...";
      if (status === "RETRY") return "Повтор...";
    }
    return "В обработке";
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>Статус парсинга</h2>
        <div className="actions">
          <button
            className="btn"
            onClick={async () => {
              try {
                setError(null);
                const fromStorage = loadJobs();
                const [count, sharedJobsRaw] = await Promise.all([getPapersCount("all"), getSharedParseJobs(50)]);
                const sharedJobs = normalizeJobs(sharedJobsRaw);

                if (count === 0 && sharedJobs.length === 0) {
                  clearParseJobStorage();
                  jobsRef.current = [];
                  setJobs([]);
                  setAllCount(0);
                  setLastUpdatedAt(Date.now());
                  return;
                }

                const merged = mergeJobs(fromStorage, sharedJobs);
                jobsRef.current = merged;
                setJobs(merged);
                saveJobs(merged);
                await refreshJobs(merged);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Обновить
          </button>
          <button className="btn btn-danger" onClick={clearHistory}>
            Очистить историю
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Текущий срез</h3>
        <p className="muted">
          Всего статей: <strong>{allCount}</strong> (обновлено:{" "}
          <strong>{new Date(lastUpdatedAt).toLocaleTimeString("ru-RU")}</strong>)
        </p>
        <div className="kpi-grid" style={{ marginTop: 10, gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
          <article className="panel kpi-card">
            <h3>В обработке</h3>
            <p className="kpi">{inProgress}</p>
          </article>
          <article className="panel kpi-card">
            <h3>Завершено</h3>
            <p className="kpi">{completed}</p>
          </article>
          <article className="panel kpi-card">
            <h3>Celery Worker</h3>
            <p className={`kpi-status ${inProgress > 0 ? "ok" : "idle"}`}>
              {inProgress > 0 ? "Активен" : "Ожидание"}
            </p>
          </article>
        </div>
        {error && <p className="error">{error}</p>}
      </div>

      <div className="panel">
        <h3>Общая история заданий парсинга</h3>
        {jobs.length === 0 ? (
          <p className="muted">История задач пустая. Запустите парсинг в разделе Главная.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Celery task_id</th>
                <th>Источник</th>
                <th>Запрос</th>
                <th>Статус</th>
                <th>Прогресс</th>
                <th>Сохранено</th>
                <th>Время</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {jobs.slice(0, 30).map((j) => {
                const progress = getProgressPercent(j);
                const statusText = getStatusText(j);
                const savedCount = j.celeryStatus?.saved_count || j.celeryStatus?.total_saved || j.celeryStatus?.result?.saved_count || j.celeryStatus?.result?.total_saved || (j.lastObservedCount - j.initialCount);

                return (
                  <tr key={j.jobId}>
                    <td style={{ wordBreak: "break-word", fontFamily: "monospace", fontSize: "0.85em" }}>
                      {j.jobId}
                    </td>
                    <td>{j.source}</td>
                    <td style={{ maxWidth: 280 }}>{j.query}</td>
                    <td>
                      <span className={`status ${j.status === "completed" || j.celeryStatus?.status === "SUCCESS" ? "active" : j.status === "failed" || j.celeryStatus?.status === "FAILURE" ? "failed" : ""}`}>
                        {statusText}
                      </span>
                    </td>
                    <td style={{ minWidth: 120 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div style={{ flex: 1, height: 8, background: "#e0e0e0", borderRadius: 4, overflow: "hidden" }}>
                          <div
                            style={{
                              width: `${progress}%`,
                              height: "100%",
                              background: progress === 100 ? "#22c55e" : "#4a6cf7",
                              transition: "width 0.3s ease",
                            }}
                          />
                        </div>
                        <span style={{ fontSize: "0.85em", minWidth: 38 }}>{progress}%</span>
                      </div>
                    </td>
                    <td>{savedCount}</td>
                    <td>{new Date(j.startedAt).toLocaleTimeString("ru-RU")}</td>
                    <td style={{ display: "flex", gap: 8 }}>
                      {j.status === "in_progress" && j.celeryStatus?.status !== "REVOKED" ? (
                        <button className="btn" onClick={() => cancelJob(j.jobId)}>
                          Остановить
                        </button>
                      ) : (
                        <button className="btn btn-danger" onClick={() => deleteJob(j.jobId)}>
                          Удалить
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ marginTop: 10 }}>
          Статус отображается в реальном времени через Celery API endpoint /api/v1/tasks/celery/{`{task_id}`}/status
        </p>
      </div>
    </div>
  );
}
