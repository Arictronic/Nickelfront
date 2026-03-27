import { useEffect, useState } from "react";
import { getPapersCount, getCeleryTaskStatus, revokeCeleryTask, deleteCeleryTask, type CeleryTaskStatus } from "../api/papers";

type ParseJob = {
  jobId: string;
  startedAt: number;
  query: string;
  source: "CORE" | "arXiv" | "all";
  initialCount: number;
  lastObservedCount: number;
  lastCountChangeAt: number;
  status: "in_progress" | "completed" | "cancelled";
  celeryStatus?: CeleryTaskStatus;
  lastPolledAt?: number;
};

const LS_KEY = "parseJobs.v1";

function loadJobs(): ParseJob[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as ParseJob[];
  } catch {
    return [];
  }
}

function saveJobs(jobs: ParseJob[]) {
  localStorage.setItem(LS_KEY, JSON.stringify(jobs));
}

export default function WorkerStatus() {
  const [jobs, setJobs] = useState<ParseJob[]>(() => loadJobs());
  const [allCount, setAllCount] = useState<number>(0);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number>(Date.now());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPapersCount("all")
      .then((c) => setAllCount(c))
      .catch((e) => setError((e as Error).message));
  }, []);

  // Polling статуса задач Celery
  useEffect(() => {
    if (jobs.length === 0) return;

    const pollInterval = window.setInterval(async () => {
      try {
        const updatedJobs = await Promise.all(
          jobs.map(async (job) => {
            // Не обновляем завершённые или отменённые задачи
            if (job.status !== "in_progress") return job;
            // Если уже отменено, не обновляем статус из API
            if (job.celeryStatus?.status === "REVOKED" || job.status === "cancelled") return job;

            try {
              const celeryStatus = await getCeleryTaskStatus(job.jobId);
              const now = Date.now();
              const isCompleted = celeryStatus.status === "SUCCESS" || celeryStatus.status === "FAILURE";
              const isRevoked = celeryStatus.status === "REVOKED";
              const savedCount = celeryStatus.saved_count || celeryStatus.result?.saved_count || 0;

              const next: ParseJob = {
                ...job,
                celeryStatus,
                lastObservedCount: savedCount > 0 ? savedCount : job.lastObservedCount,
                lastCountChangeAt: isCompleted ? now : job.lastCountChangeAt,
                lastPolledAt: now,
                status: isRevoked ? "cancelled" : isCompleted ? "completed" : "in_progress",
              };

              return next;
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
              }
              return next;
            }
          })
        );

        setJobs(updatedJobs);
        saveJobs(updatedJobs);
        const total = await getPapersCount("all");
        setAllCount(total);
        setLastUpdatedAt(Date.now());
      } catch (e) {
        setError((e as Error).message);
      }
    }, 5000);

    return () => window.clearInterval(pollInterval);
  }, [jobs.length]);

  const inProgress = jobs.filter((j) => j.status === "in_progress").length;
  const completed = jobs.filter((j) => j.status === "completed").length;

  const clearHistory = () => {
    if (!window.confirm("Очистить историю задач в интерфейсе? (не влияет на celery)")) return;
    setJobs([]);
    localStorage.removeItem(LS_KEY);
  };

  const cancelJob = async (jobId: string) => {
    if (!window.confirm("Остановить задачу? В очереди она будет отменена, а запущенная может не прерваться сразу.")) {
      return;
    }

    try {
      await revokeCeleryTask(jobId, false);
      const nextJobs = jobs.map((job) =>
        job.jobId === jobId
          ? {
              ...job,
              status: "cancelled",
              celeryStatus: {
                ...(job.celeryStatus || {}),
                status: "REVOKED",
                state: "REVOKED",
              },
            }
          : job
      );
      setJobs(nextJobs);
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
      // Вызываем API для удаления флага отмены (опционально)
      await deleteCeleryTask(jobId);
      const nextJobs = jobs.filter((job) => job.jobId !== jobId);
      setJobs(nextJobs);
      saveJobs(nextJobs);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const getProgressPercent = (job: ParseJob): number => {
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
    if (job.status === "cancelled") return "Отменено";
    return job.status === "completed" ? "Готово" : "В обработке";
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>Статус парсинга</h2>
        <div className="actions">
          <button className="btn" onClick={() => setJobs(loadJobs())}>
            Перезагрузить
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
            <h3>Завершено (ваши)</h3>
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
        <h3>Ваши задания парсинга</h3>
        {jobs.length === 0 ? (
          <p className="muted">История задач пустая. Запустите парсинг в разделе Dashboard.</p>
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
                const savedCount = j.celeryStatus?.saved_count || j.celeryStatus?.result?.saved_count || (j.lastObservedCount - j.initialCount);

                return (
                  <tr key={j.jobId}>
                    <td style={{ wordBreak: "break-word", fontFamily: "monospace", fontSize: "0.85em" }}>
                      {j.jobId}
                    </td>
                    <td>{j.source}</td>
                    <td style={{ maxWidth: 280 }}>{j.query}</td>
                    <td>
                      <span className={`status ${j.status === "completed" || j.celeryStatus?.status === "SUCCESS" ? "active" : ""}`}>
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
