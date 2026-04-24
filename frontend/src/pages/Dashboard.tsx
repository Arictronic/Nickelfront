import { useEffect, useMemo, useState } from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, PieChart, Pie, Cell, CartesianGrid } from "recharts";
import { getPapersCount, getPapersList, parseAll, parsePapers } from "../api/papers";
import { Paper } from "../types/paper";
import { Link } from "react-router-dom";

const COLORS = ["#ffffff", "#cfcfd6", "#8e8e98"];

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

export default function Dashboard() {
  const [totalPapers, setTotalPapers] = useState(0);
  const [latest, setLatest] = useState<Paper[]>([]);
  const [jobs, setJobs] = useState<ParseJob[]>(() => loadJobs());

  const [query, setQuery] = useState("nickel-based superalloys");
  const [source, setSource] = useState<"CORE" | "arXiv">("CORE");
  const [limit, setLimit] = useState(25);
  const [parsingError, setParsingError] = useState<string | null>(null);

  const [updatedAt, setUpdatedAt] = useState(new Date());

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
    const count = await getPapersCount("all");
    setTotalPapers(count);
    const latestPapers = await getPapersList({ limit: 5, offset: 0, source: "all" });
    setLatest(latestPapers);
  };

  useEffect(() => {
    fetchPage().catch(() => {
      // initial load errors - just keep empty UI
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Heuristic "реальное время": celery-status отсутствует в API, поэтому ориентируемся на рост papers count.
  useEffect(() => {
    if (jobs.length === 0) return;

    const interval = window.setInterval(async () => {
      try {
        const updatedJobs = await Promise.all(
          jobs.map(async (job) => {
            if (job.status === "completed") return job;

            const current = await getPapersCount(job.source === "all" ? "all" : job.source);
            const now = Date.now();
            const changed = current !== job.lastObservedCount;

            const next: ParseJob = {
              ...job,
              lastObservedCount: current,
              lastCountChangeAt: changed ? now : job.lastCountChangeAt,
            };

            const stableMs = 60_000; // считаем completed, если count стабилен 1 минуту и вырос
            if (now - next.lastCountChangeAt > stableMs && current > next.initialCount) {
              next.status = "completed";
            }

            return next;
          })
        );

        setJobs(updatedJobs);
        saveJobs(updatedJobs);
      } catch {
        // ignore polling errors
      }
    }, 10_000);

    return () => window.clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs.length]);

  const lineData = useMemo(() => {
    // Demo chart: last 10 dates from latest list (no DB-level aggregation endpoint)
    return latest
      .map((p) => ({ date: (p.publicationDate ?? "").slice(0, 10), count: 1 }))
      .filter((x) => x.date)
      .slice(0, 10);
  }, [latest]);

  const pieData = useMemo(() => {
    const bySource = latest.reduce<Record<string, number>>((acc, p) => {
      const key = p.source;
      acc[key] = (acc[key] ?? 0) + 1;
      return acc;
    }, {});

    return Object.entries(bySource).map(([name, value]) => ({ name, value }));
  }, [latest]);

  const startParsing = async () => {
    setParsingError(null);
    try {
      const currentCount = await getPapersCount(source);
      const res = await parsePapers({ query, limit, source });

      const job: ParseJob = {
        jobId: String(res.task_id),
        startedAt: Date.now(),
        query: res.query,
        source: res.source as "CORE" | "arXiv",
        initialCount: currentCount,
        lastObservedCount: currentCount,
        lastCountChangeAt: Date.now(),
        status: "in_progress",
      };

      const nextJobs = [job, ...jobs].slice(0, 30);
      setJobs(nextJobs);
      saveJobs(nextJobs);
    } catch (e) {
      setParsingError((e as Error).message);
    }
  };

  const startParsingAll = async () => {
    setParsingError(null);
    try {
      const currentCount = await getPapersCount("all");
      const res = await parseAll({ limitPerQuery: limit, source: "all" });

      const job: ParseJob = {
        jobId: String(res.task_id),
        startedAt: Date.now(),
        query: "ALL_SOURCES",
        source: "all",
        initialCount: currentCount,
        lastObservedCount: currentCount,
        lastCountChangeAt: Date.now(),
        status: "in_progress",
      };

      const nextJobs = [job, ...jobs].slice(0, 30);
      setJobs(nextJobs);
      saveJobs(nextJobs);
    } catch (e) {
      setParsingError((e as Error).message);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>Dashboard</h2>
        <div className="actions">
          <button className="btn" onClick={() => fetchPage()}>
            Обновить данные
          </button>
          <button className="btn btn-primary" onClick={startParsing}>
            Запустить парсинг статей
          </button>
          <button className="btn" onClick={startParsingAll}>
            Парсинг по всем шаблонам
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Параметры парсинга</h3>
        <div className="filters">
          <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поисковый запрос" />
          <select value={source} onChange={(e) => setSource(e.target.value as "CORE" | "arXiv")}>
            <option value="CORE">CORE</option>
            <option value="arXiv">arXiv</option>
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
          <span className="muted">Статус показывает рост числа статей (в API нет celery-status по task_id).</span>
        </div>
        {parsingError && <p className="error">{parsingError}</p>}
      </div>

      <div className="kpi-grid">
        <article className="panel kpi-card">
          <h3>Всего статей</h3>
          <p className="kpi">{totalPapers}</p>
        </article>
        <article className="panel kpi-card">
          <h3>За сегодня (по последним добавлениям)</h3>
          <p className="kpi">{todayPapers}</p>
        </article>
        <article className="panel kpi-card">
          <h3>В обработке</h3>
          <p className={`kpi-status ${activeJobsCount > 0 ? "ok" : "idle"}`}>{activeJobsCount}</p>
        </article>
        <article className="panel kpi-card">
          <h3>Завершено (ваши)</h3>
          <p className="kpi">{completedJobsCount}</p>
        </article>
      </div>

      <div className="chart-grid">
        <article className="panel chart-panel">
          <div className="chart-panel-head">
            <div>
              <p className="chart-overline">Live signal</p>
              <h3>Поток последних публикаций</h3>
            </div>
            <span className="counter-badge">{lineData.length || 1} точек</span>
          </div>
          <div className="chart-shell">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={lineData.length ? lineData : [{ date: "—", count: 0 }]} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
                <defs>
                  <linearGradient id="lineGlow" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#7a7a85" />
                    <stop offset="55%" stopColor="#ffffff" />
                    <stop offset="100%" stopColor="#b8b8c2" />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "#8e8e98", fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#8e8e98", fontSize: 12 }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{
                    borderRadius: 18,
                    border: "1px solid rgba(255,255,255,0.12)",
                    background: "rgba(10,10,12,0.88)",
                    backdropFilter: "blur(18px)",
                    color: "#ffffff",
                  }}
                />
                <Line type="monotone" dataKey="count" stroke="url(#lineGlow)" strokeWidth={3.5} dot={{ r: 0 }} activeDot={{ r: 6, fill: "#ffffff", stroke: "rgba(255,255,255,0.2)", strokeWidth: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </article>
        <article className="panel chart-panel">
          <div className="chart-panel-head">
            <div>
              <p className="chart-overline">Distribution</p>
              <h3>Источники данных</h3>
            </div>
            <span className="counter-badge">{pieData.length || 1} сегмента</span>
          </div>
          <div className="chart-shell chart-shell-pie">
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Tooltip
                  contentStyle={{
                    borderRadius: 18,
                    border: "1px solid rgba(255,255,255,0.12)",
                    background: "rgba(10,10,12,0.88)",
                    backdropFilter: "blur(18px)",
                    color: "#ffffff",
                  }}
                />
                <Pie
                  data={pieData.length ? pieData : [{ name: "нет данных", value: 1 }]}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={48}
                  outerRadius={86}
                  paddingAngle={6}
                  stroke="rgba(255,255,255,0.08)"
                  strokeWidth={1}
                >
                  {(pieData.length ? pieData : [{ name: "нет данных", value: 1 }]).map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
        </article>
      </div>

      <div className="panel">
        <h3>Последние добавленные</h3>
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Название</th>
              <th>Источник</th>
              <th>Дата</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {latest.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  Пока нет данных. Запустите парсинг.
                </td>
              </tr>
            ) : (
              latest.map((p) => (
                <tr key={p.id}>
                  <td>{p.id}</td>
                  <td style={{ maxWidth: 520 }}>{p.title}</td>
                  <td>{p.source}</td>
                  <td>{p.publicationDate ? p.publicationDate.slice(0, 10) : "—"}</td>
                  <td>
                    <Link className="action-link" to={`/papers/${p.id}`}>
                      Открыть
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        <p className="muted">Обновлено: {updatedAt.toLocaleTimeString("ru-RU")}</p>
      </div>

      <div className="panel">
        <h3>Ваши парсинг-задачи (статус)</h3>
        {jobs.length === 0 ? (
          <p className="muted">Задачи появятся после запуска парсинга.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Celery task_id</th>
                <th>Источник</th>
                <th>Запрос</th>
                <th>Статус</th>
                <th>Счетчик</th>
              </tr>
            </thead>
            <tbody>
              {jobs.slice(0, 10).map((j) => (
                <tr key={j.jobId}>
                  <td style={{ wordBreak: "break-word" }}>{j.jobId}</td>
                  <td>{j.source}</td>
                  <td style={{ maxWidth: 360 }}>{j.query}</td>
                  <td>
                    <span className={`status ${j.status === "completed" ? "active" : ""}`}>
                      {j.status === "completed" ? "Готово" : "В обработке"}
                    </span>
                  </td>
                  <td>
                    {j.lastObservedCount} (было {j.initialCount})
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
