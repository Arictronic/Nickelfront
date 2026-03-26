import { useEffect, useMemo, useRef, useState } from "react";
import { getPapersCount } from "../api/papers";

type ParseJob = {
  jobId: string;
  startedAt: number;
  query: string;
  source: "CORE" | "arXiv" | "all";
  initialCount: number;
  lastObservedCount: number;
  lastCountChangeAt: number;
  status: "in_progress" | "completed";
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
  const jobsRef = useRef<ParseJob[]>(jobs);
  const [allCount, setAllCount] = useState<number>(0);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number>(Date.now());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  useEffect(() => {
    getPapersCount("all")
      .then((c) => setAllCount(c))
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (jobs.length === 0) return;

    const interval = window.setInterval(async () => {
      try {
        const snapshot = jobsRef.current;
        const updatedJobs = await Promise.all(
          snapshot.map(async (job) => {
            if (job.status === "completed") return job;
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
    }, 10_000);

    return () => window.clearInterval(interval);
  }, [jobs.length]);

  const inProgress = useMemo(() => jobs.filter((j) => j.status === "in_progress").length, [jobs]);
  const completed = useMemo(() => jobs.filter((j) => j.status === "completed").length, [jobs]);

  const clearHistory = () => {
    if (!window.confirm("Очистить историю задач в интерфейсе? (не влияет на celery)")) return;
    setJobs([]);
    localStorage.removeItem(LS_KEY);
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
            <h3>Worker realtime</h3>
            <p className="kpi-status idle">нет endpoint</p>
          </article>
        </div>
        {error && <p className="error">{error}</p>}
      </div>

      <div className="panel">
        <h3>Ваши задания парсинга (heuristic)</h3>
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
                <th>Счетчик</th>
                <th>Время</th>
              </tr>
            </thead>
            <tbody>
              {jobs.slice(0, 30).map((j) => (
                <tr key={j.jobId}>
                  <td style={{ wordBreak: "break-word" }}>{j.jobId}</td>
                  <td>{j.source}</td>
                  <td style={{ maxWidth: 360 }}>{j.query}</td>
                  <td>
                    <span className={`status ${j.status === "completed" ? "active" : ""}`}>{j.status === "completed" ? "Готово" : "В обработке"}</span>
                  </td>
                  <td>
                    {j.lastObservedCount} (было {j.initialCount})
                  </td>
                  <td>{new Date(j.startedAt).toLocaleTimeString("ru-RU")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ marginTop: 10 }}>
          Примечание: в текущем бэке нет API для статуса celery задачи по `task_id`, поэтому статус оценивается эвристически по росту общего числа статей.
        </p>
      </div>
    </div>
  );
}

