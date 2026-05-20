import { useEffect, useMemo, useRef, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, PieChart, Pie, Cell, CartesianGrid, ResponsiveContainer } from "recharts";
import {
  getPapersCount,
  getPapersList,
  parseAll,
  parsePapers,
  getCeleryTaskStatus,
  revokeCeleryTask,
  deleteCeleryTask,
} from "../api/papers";
import { PAPER_SOURCES, Paper, PaperSource } from "../types/paper";
import { Link } from "react-router-dom";

// Дорогая кибер-палитра для круговой диаграммы (как на концепте)
const COLORS = ["#1d4ed8", "#3b82f6", "#60a5fa", "#93c5fd", "#e2e8f0"];

type ParseJob = {
  jobId: string;
  startedAt: number;
  query: string;
  source: PaperSource | "all";
  initialCount: number;
  lastObservedCount: number;
  lastCountChangeAt: number;
  status: "in_progress" | "completed" | "cancelled";
  celeryStatus?: any;
};

const LS_KEY = "parseJobs.v4";
const LEGACY_LS_KEYS = ["parseJobs.v3", "parseJobs.v2", "parseJobs.v1"];
const LS_RESET_MARK = "parseJobs.reset.v1";

function clearAllParseJobKeys() {
  const toDelete: string[] = [];
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (key && key.startsWith("parseJobs.")) {
      toDelete.push(key);
    }
  }
  toDelete.forEach((key) => localStorage.removeItem(key));
}

function loadJobs(): ParseJob[] {
  try {
    if (!localStorage.getItem(LS_RESET_MARK)) {
      clearAllParseJobKeys();
      localStorage.setItem(LS_RESET_MARK, "1");
    }
    for (const key of LEGACY_LS_KEYS) localStorage.removeItem(key);
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

export default function Dashboard() {
  const [totalPapers, setTotalPapers] = useState(0);
  const [latest, setLatest] = useState<Paper[]>([]);
  const [sourceCounts, setSourceCounts] = useState<Record<string, number>>({});
  const [jobs, setJobs] = useState<ParseJob[]>(() => loadJobs());

  const [query, setQuery] = useState("nickel-based superalloys");
  const [source, setSource] = useState<PaperSource | "all">("arXiv");
  const [limit, setLimit] = useState(25);
  const [parsingError, setParsingError] = useState<string | null>(null);

  const [updatedAt, setUpdatedAt] = useState(new Date());
  const jobsRef = useRef<ParseJob[]>(jobs);

  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  useEffect(() => {
    const id = window.setInterval(() => setUpdatedAt(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const activeJobsCount = jobs.filter((j) => j.status === "in_progress").length;
  const completedJobsCount = jobs.filter((j) => j.status === "completed").length;

  const todayString = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const todayPapers = useMemo(
    () => latest.filter((p) => (p.publicationDate ?? "").slice(0, 10) === todayString).length,
    [latest, todayString]
  );

  const fetchPage = async () => {
    const [count, latestPapers, sourceEntries] = await Promise.all([
      getPapersCount("all"),
      getPapersList({ limit: 300, offset: 0, source: "all" }),
      Promise.all(PAPER_SOURCES.map(async (src) => [src, await getPapersCount(src)] as const)),
    ]);
    setTotalPapers(count);
    setLatest(latestPapers);
    setSourceCounts(Object.fromEntries(sourceEntries));
  };

  useEffect(() => {
    fetchPage().catch(() => {
      // initial load errors - just keep empty UI
    });
  }, []);

  useEffect(() => {
    const interval = window.setInterval(async () => {
      const currentJobs = jobsRef.current;
      if (currentJobs.length === 0) return;

      try {
        const updatedJobs = await Promise.all(
          currentJobs.map(async (job) => {
            if (job.status !== "in_progress") return job;
            if (job.celeryStatus?.status === "REVOKED") return job;

            try {
              const celeryStatus = await getCeleryTaskStatus(job.jobId);
              const now = Date.now();
              const isCompleted = celeryStatus.status === "SUCCESS" || celeryStatus.status === "FAILURE";
              const isRevoked = celeryStatus.status === "REVOKED";
              const savedCount = celeryStatus.saved_count || celeryStatus.result?.saved_count || 0;

              if (celeryStatus.status === "PENDING") {
                const current = await getPapersCount(job.source === "all" ? "all" : job.source);
                const changed = current !== job.lastObservedCount;
                const lastCountChangeAt = changed ? now : job.lastCountChangeAt;
                const stableMs = 60_000;
                const shouldComplete = now - lastCountChangeAt > stableMs && current > job.initialCount;

                return {
                  ...job,
                  celeryStatus,
                  lastObservedCount: current,
                  lastCountChangeAt,
                  status: shouldComplete ? "completed" : "in_progress",
                } as ParseJob;
              }

              return {
                ...job,
                celeryStatus,
                lastObservedCount: savedCount > 0 ? savedCount : job.lastObservedCount,
                lastCountChangeAt: isCompleted ? now : job.lastCountChangeAt,
                status: isRevoked ? "cancelled" : isCompleted ? "completed" : "in_progress",
              } as ParseJob;
            } catch {
              const current = await getPapersCount(job.source === "all" ? "all" : job.source);
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
      } catch {
        // ignore polling errors
      }
    }, 5000);

    return () => window.clearInterval(interval);
  }, []);

  const lineData = useMemo(() => {
    const byDate = latest.reduce<Record<string, number>>((acc, p) => {
      const parsedDate = (p.createdAt ?? p.updatedAt ?? p.publicationDate ?? "").slice(0, 10);
      if (!parsedDate) return acc;
      acc[parsedDate] = (acc[parsedDate] ?? 0) + 1;
      return acc;
    }, {});
    return Object.entries(byDate)
      .map(([date, count]) => ({ date, count }))
      .sort((a, b) => a.date.localeCompare(b.date));
  }, [latest]);

  const pieData = useMemo(() => {
    return Object.entries(sourceCounts)
      .map(([name, value]) => ({ name, value }))
      .filter((item) => item.value > 0);
  }, [sourceCounts]);

  const startParsing = async () => {
    setParsingError(null);
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      setParsingError("Поле поискового запроса обязательно");
      return;
    }
    try {
      const currentCount = await getPapersCount(source);
      let job: ParseJob;
      if (source === "all") {
        const res = await parseAll({
          limitPerQuery: limit,
          source: "all",
          query: normalizedQuery,
        });
        job = {
          jobId: String(res.task_id),
          startedAt: Date.now(),
          query: normalizedQuery,
          source: "all",
          initialCount: currentCount,
          lastObservedCount: currentCount,
          lastCountChangeAt: Date.now(),
          status: "in_progress",
        };
      } else {
        const res = await parsePapers({ query: normalizedQuery, limit, source });
        job = {
          jobId: String(res.task_id),
          startedAt: Date.now(),
          query: res.query,
          source: res.source as PaperSource,
          initialCount: currentCount,
          lastObservedCount: currentCount,
          lastCountChangeAt: Date.now(),
          status: "in_progress",
        };
      }

      setJobs((prev) => {
        const nextJobs = [job, ...prev].slice(0, 30);
        saveJobs(nextJobs);
        return nextJobs;
      });
    } catch (e) {
      setParsingError((e as Error).message);
    }
  };

  const cancelJob = async (jobId: string) => {
    if (!window.confirm("Остановить задачу? В очереди она будет отменена, а запущенная может не прерваться сразу.")) {
      return;
    }

    try {
      await revokeCeleryTask(jobId, false);
      setJobs((prev) => {
        const nextJobs = prev.map((job): ParseJob => {
          if (job.jobId !== jobId) return job;
          return {
            ...job,
            status: "cancelled",
            celeryStatus: {
              ...(job.celeryStatus || {}),
              status: "REVOKED",
              state: "REVOKED",
            },
          };
        });
        saveJobs(nextJobs);
        return nextJobs;
      });
    } catch (e) {
      setParsingError((e as Error).message);
    }
  };

  const deleteJob = async (jobId: string) => {
    if (!window.confirm("Удалить задачу из истории? Это не повлияет на Celery, только удалит запись из интерфейса.")) {
      return;
    }

    try {
      await deleteCeleryTask(jobId);
      setJobs((prev) => {
        const nextJobs = prev.filter((job) => job.jobId !== jobId);
        saveJobs(nextJobs);
        return nextJobs;
      });
    } catch (e) {
      setParsingError((e as Error).message);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>Панель</h2>
        <div className="actions">
          <button className="btn btn-primary" onClick={startParsing}>
            Запустить парсинг статей
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Параметры парсинга</h3>
        <div className="filters" style={{ background: "transparent", border: "none", padding: 0 }}>
          <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поисковый запрос" style={{ flex: 2 }} />
          <select className="input" value={source} onChange={(e) => setSource(e.target.value as PaperSource | "all")} style={{ flex: 1 }}>
            <option value="all">Все шаблоны</option>
            {PAPER_SOURCES.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>
          <input
            className="input"
            type="number"
            min={1}
            max={100}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={{ width: 120 }}
          />
        </div>
        {parsingError && <p className="error" style={{ marginTop: 12 }}>{parsingError}</p>}
      </div>

      {/* Сетка KPI-индикаторов */}
      <div className="kpi-grid">
        <article className="panel kpi-card">
          <h3>Всего статей</h3>
          <p className="kpi">{totalPapers}</p>
        </article>
        <article className="panel kpi-card">
          <h3>За сегодня</h3>
          <p className="kpi">{todayPapers}</p>
        </article>
        <article className="panel kpi-card">
          <h3>В обработке</h3>
          <div style={{ marginTop: 12 }}>
            <span className={`session-status ${activeJobsCount > 0 ? "checking" : "inactive"}`}>
              <span className="session-dot"></span>
              {activeJobsCount} активных
            </span>
          </div>
        </article>
        <article className="panel kpi-card">
          <h3>Завершено задач</h3>
          <p className="kpi">{completedJobsCount}</p>
        </article>
      </div>

      {/* Графики в стиле премиального UI с концепта */}
      <div className="chart-grid">
        <article className="panel" style={{ minHeight: 320 }}>
          <h3>Динамика парсинга (добавление по датам)</h3>
          <div style={{ width: "100%", height: 240, marginTop: 16 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={lineData.length ? lineData : [{ date: "—", count: 0 }]} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  {/* Плавный неоновый градиент для волны */}
                  <linearGradient id="chartGlow" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" stroke="var(--muted)" style={{ fontSize: 11, fontFamily: "monospace" }} />
                <YAxis stroke="var(--muted)" style={{ fontSize: 11, fontFamily: "monospace" }} />
                <Tooltip
                  contentStyle={{ background: "var(--surface-2)", borderColor: "var(--border)", borderRadius: 8, color: "var(--text)" }}
                  itemStyle={{ color: "var(--text)" }}
                />
                <Area type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={2} fillOpacity={1} fill="url(#chartGlow)" dot={{ r: 3, strokeWidth: 1, fill: "var(--bg)" }} activeDot={{ r: 6 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="panel" style={{ minHeight: 320 }}>
          <h3>Распределение по источникам</h3>
          <div style={{ width: "100%", height: 240, marginTop: 16, display: "flex", justifyContent: "center", alignItems: "center" }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData.length ? pieData : [{ name: "нет данных", value: 1 }]}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={60}
                  outerRadius={85}
                  paddingAngle={4}
                >
                  {(pieData.length ? pieData : [{ name: "нет данных", value: 1 }]).map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} stroke="var(--surface)" strokeWidth={2} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "var(--surface-2)", borderColor: "var(--border)", borderRadius: 8 }}
                  itemStyle={{ color: "var(--text)" }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </article>
      </div>

      {/* Таблица последних документов */}
      <div className="panel">
        <h3>Последние добавленные документы</h3>
        <div style={{ overflowX: "auto", marginTop: 12 }}>
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: "80px" }}>ID</th>
                <th>Название</th>
                <th style={{ width: "140px" }}>Источник</th>
                <th style={{ width: "140px" }}>Дата публикации</th>
                <th style={{ width: "100px", textAlign: "right" }}>Действия</th>
              </tr>
            </thead>
            <tbody>
              {latest.length === 0 ? (
                <tr>
                  <td colSpan={5} className="muted" style={{ textAlign: "center", padding: "24px 0" }}>
                    Пока нет данных. Запустите парсинг для наполнения базы.
                  </td>
                </tr>
              ) : (
                latest.slice(0, 10).map((p) => (
                  <tr key={p.id}>
                    <td className="muted" style={{ fontFamily: "monospace" }}>{p.id}</td>
                    <td style={{ fontWeight: 500 }}>{p.title}</td>
                    <td><span className="user-chip" style={{ fontSize: "12px", padding: "4px 10px" }}>{p.source}</span></td>
                    <td className="muted">{p.publicationDate ? p.publicationDate.slice(0, 10) : "—"}</td>
                    <td style={{ textAlign: "right" }}>
                      <Link className="action-link" to={`/papers/${p.id}`}>
                        Открыть
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ marginTop: 14 }}>Синхронизировано: {updatedAt.toLocaleTimeString("ru-RU")}</p>
      </div>

      {/* Текущие фоновые процессы парсинга */}
      <div className="panel">
        <h3>Мониторинг процессов Celery</h3>
        {jobs.length === 0 ? (
          <p className="muted" style={{ padding: "12px 0 0" }}>Задачи появятся после запуска фонового парсинга.</p>
        ) : (
          <div style={{ overflowX: "auto", marginTop: 16 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Celery ID</th>
                  <th>Провайдер</th>
                  <th>Ключевой запрос</th>
                  <th>Статус</th>
                  <th style={{ width: "200px" }}>Индикатор прогресса</th>
                  <th>Найдено</th>
                  <th style={{ textAlign: "right" }}>Управление</th>
                </tr>
              </thead>
              <tbody>
                {jobs.slice(0, 10).map((j) => {
                  const progress = (() => {
                    if (j.status === "completed") return 100;
                    if (j.celeryStatus) {
                      const current = j.celeryStatus.current || j.celeryStatus.result?.current || 0;
                      const total = j.celeryStatus.total || j.celeryStatus.result?.total || 0;
                      if (total > 0) return Math.round((current / total) * 100);
                    }
                    const delta = j.lastObservedCount - j.initialCount;
                    return Math.min(100, Math.round((delta / 50) * 100));
                  })();

                  const statusText = (() => {
                    if (j.status === "completed") return "✓ Готово";
                    if (j.status === "cancelled") return "Отменено";
                    if (j.celeryStatus) {
                      const status = j.celeryStatus.status;
                      if (status === "SUCCESS") return "✓ Готово";
                      if (status === "FAILURE") return "✕ Сбой";
                      if (status === "REVOKED") return "Отменено";
                      if (status === "PENDING") return "Очередь";
                      if (status === "STARTED") return j.celeryStatus.result?.status || "Парсинг...";
                    }
                    return "В обработке";
                  })();

                  const isJobActive = j.status === "in_progress" && j.celeryStatus?.status !== "REVOKED";
                  const savedCount = j.celeryStatus?.saved_count || j.celeryStatus?.result?.saved_count || (j.lastObservedCount - j.initialCount);

                  return (
                    <tr key={j.jobId}>
                      <td className="muted" style={{ fontFamily: "monospace", fontSize: "12px" }}>{j.jobId.slice(0, 8)}...</td>
                      <td><span className="user-chip" style={{ fontSize: "11px", padding: "2px 8px" }}>{j.source}</span></td>
                      <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.query}</td>
                      <td>
                        <span className={`status ${j.status === "completed" || j.celeryStatus?.status === "SUCCESS" ? "active" : j.status === "cancelled" ? "expired" : ""}`}>
                          {statusText}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          {/* Красивый кастомный прогресс-бар с анимацией */}
                          <div style={{ flex: 1, height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" }}>
                            <div
                              style={{
                                width: `${progress}%`,
                                height: "100%",
                                background: progress === 100 ? "#22c55e" : "#3b82f6",
                                boxShadow: progress === 100 ? "0 0 8px rgba(34,197,94,0.4)" : "0 0 8px rgba(59,130,246,0.4)",
                                transition: "width 0.4s cubic-bezier(0.4, 0, 0.2, 1)",
                              }}
                            />
                          </div>
                          <span style={{ fontSize: "12px", fontFamily: "monospace", minWidth: 32 }}>{progress}%</span>
                        </div>
                      </td>
                      <td style={{ fontWeight: 600 }}>{savedCount}</td>
                      <td style={{ textAlign: "right" }}>
                        {isJobActive ? (
                          <button className="btn" onClick={() => cancelJob(j.jobId)} style={{ padding: "6px 12px", fontSize: "12px" }}>
                            Прервать
                          </button>
                        ) : (
                          <button className="btn btn-danger" onClick={() => deleteJob(j.jobId)} style={{ padding: "6px 12px", fontSize: "12px" }}>
                            Удалить
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}