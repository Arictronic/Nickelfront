import { useEffect, useMemo, useRef, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, PieChart, Pie, Cell, LineChart, Line, ResponsiveContainer, Legend } from "recharts";
import {
  getPapersCount,
  getPapersList,
  parseAll,
  parsePapers,
  getCeleryTaskStatus,
  revokeCeleryTask,
  deleteCeleryTask,
  getSharedParseJobs,
  deleteSharedParseJob,
} from "../api/papers";
import { PAPER_SOURCES, Paper, PaperSource } from "../types/paper";
import { Link } from "react-router-dom";
import { apiClient } from "../api/client";

const COLORS = ["#4a6cf7", "#00c49f", "#ffbb28", "#ff8042", "#8884d8"];
const COMPLETENESS_LABELS_RU: Record<string, string> = {
  with_abstract: "Аннотация",
  with_full_text: "Полный текст",
  with_keywords: "Ключевые слова",
  with_doi: "DOI",
  with_authors: "Авторы",
  with_embedding: "Эмбеддинг",
};

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

type AnalyticsSummary = {
  total_papers: number;
  papers_by_source: Record<string, number>;
  papers_with_embedding: number;
  embedding_coverage: number;
  avg_quality_score: number;
};

type TrendData = {
  period: string;
  count: number;
};

type TopItem = {
  name: string;
  count: number;
};

type QualityReport = {
  total: number;
  completeness: Record<string, { count: number; percent: number }>;
  averages: {
    avg_abstract_length: number;
    avg_keywords_count: number;
  };
  quality_score: {
    avg: number;
    min: number;
    max: number;
  };
};

const LS_KEY = "parseJobs.v6";
const LEGACY_LS_KEYS = ["parseJobs.v5", "parseJobs.v4", "parseJobs.v3", "parseJobs.v2", "parseJobs.v1"];
const LS_RESET_MARK = "parseJobs.reset.v3";

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

function mergeJobs(localJobs: ParseJob[], sharedJobs: ParseJob[]): ParseJob[] {
  const byId = new Map<string, ParseJob>();
  for (const job of [...sharedJobs, ...localJobs]) {
    byId.set(job.jobId, {
      ...job,
      source: job.source as PaperSource | "all",
      status: job.status as ParseJob["status"],
    });
  }
  return Array.from(byId.values()).sort((a, b) => b.startedAt - a.startedAt).slice(0, 50);
}

function normalizeQualityReport(data: any): QualityReport | null {
  if (!data) return null;
  const completeness = data.completeness ?? data.quality_metrics ?? {};
  const averages = data.averages ?? {
    avg_abstract_length: 0,
    avg_keywords_count: 0,
  };
  const quality_score = data.quality_score ?? { avg: 0, min: 0, max: 0 };

  return {
    total: data.total ?? 0,
    completeness,
    averages,
    quality_score,
  };
}

export default function Dashboard() {
  const [totalPapers, setTotalPapers] = useState(0);
  const [latest, setLatest] = useState<Paper[]>([]);
  const [jobs, setJobs] = useState<ParseJob[]>(() => loadJobs());
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [trend, setTrend] = useState<TrendData[]>([]);
  const [topJournals, setTopJournals] = useState<TopItem[]>([]);
  const [topKeywords, setTopKeywords] = useState<TopItem[]>([]);
  const [topAuthors, setTopAuthors] = useState<TopItem[]>([]);
  const [sourceDistribution, setSourceDistribution] = useState<Record<string, { count: number; percent: number }>>({});
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);

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
    const [countRes, latestRes, summaryRes, trendRes, journalsRes, keywordsRes, authorsRes, sourceRes, qualityRes] = await Promise.allSettled([
      getPapersCount("all"),
      getPapersList({ limit: 300, offset: 0, source: "all" }),
      apiClient.get<AnalyticsSummary>("/analytics/metrics/summary"),
      apiClient.get<{ trend: TrendData[] }>("/analytics/metrics/trend?group_by=month&limit=12"),
      apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=journals&limit=10"),
      apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=keywords&limit=15"),
      apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=authors&limit=10"),
      apiClient.get<{ distribution: Record<string, { count: number; percent: number }> }>("/analytics/metrics/source-distribution"),
      apiClient.get<QualityReport>("/analytics/metrics/quality-report"),
    ]);
    setTotalPapers(countRes.status === "fulfilled" ? countRes.value : 0);
    setLatest(latestRes.status === "fulfilled" ? latestRes.value : []);
    setSummary(summaryRes.status === "fulfilled" ? summaryRes.value.data ?? null : null);
    setTrend(trendRes.status === "fulfilled" ? trendRes.value.data?.trend ?? [] : []);
    setTopJournals(journalsRes.status === "fulfilled" ? journalsRes.value.data?.items ?? [] : []);
    setTopKeywords(keywordsRes.status === "fulfilled" ? keywordsRes.value.data?.items ?? [] : []);
    setTopAuthors(authorsRes.status === "fulfilled" ? authorsRes.value.data?.items ?? [] : []);
    setSourceDistribution(sourceRes.status === "fulfilled" ? sourceRes.value.data?.distribution ?? {} : {});
    setQualityReport(qualityRes.status === "fulfilled" ? normalizeQualityReport(qualityRes.value.data) : null);
  };

  useEffect(() => {
    fetchPage().catch(() => {
      // initial load errors - just keep empty UI
    });
    getSharedParseJobs(50)
      .then((sharedJobs) => {
        setJobs((current) => {
          const merged = mergeJobs(current, sharedJobs as ParseJob[]);
          saveJobs(merged);
          return merged;
        });
      })
      .catch(() => null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Реальное время: берем статус из Celery API, иначе fallback на рост papers count.
  useEffect(() => {
    const interval = window.setInterval(async () => {
      const currentJobs = jobsRef.current;
      if (currentJobs.length === 0) return;

      try {
        const updatedJobs = await Promise.all(
          currentJobs.map(async (job) => {
            // Не обновляем завершённые или отменённые задачи
            if (job.status !== "in_progress") return job;
            // Если уже отменено в Celery, не обновляем статус из API
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

                const next: ParseJob = {
                  ...job,
                  celeryStatus,
                  lastObservedCount: current,
                  lastCountChangeAt,
                  status: shouldComplete ? "completed" : "in_progress",
                };

                return next;
              }

              const next: ParseJob = {
                ...job,
                celeryStatus,
                lastObservedCount: savedCount > 0 ? savedCount : job.lastObservedCount,
                lastCountChangeAt: isCompleted ? now : job.lastCountChangeAt,
                status: isRevoked ? "cancelled" : isCompleted ? "completed" : "in_progress",
              };

              return next;
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

  const sourcePieData = useMemo(
    () =>
      Object.entries(sourceDistribution ?? {}).map(([name, data]) => ({
        name,
        value: data.count,
      })),
    [sourceDistribution]
  );

  const qualityData = useMemo(
    () =>
      qualityReport
        ? Object.entries(qualityReport.completeness ?? {}).map(([key, data]) => ({
            name: COMPLETENESS_LABELS_RU[key] ?? key.replace("with_", "").replaceAll("_", " "),
            percent: data.percent,
          }))
        : [],
    [qualityReport]
  );

  const avgCompleteness = useMemo(() => {
    if (!qualityData.length) return 0;
    const sum = qualityData.reduce((acc, item) => acc + item.percent, 0);
    return Number((sum / qualityData.length).toFixed(1));
  }, [qualityData]);

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

      setJobs((prev: ParseJob[]): ParseJob[] => {
        const nextJobs: ParseJob[] = [job, ...prev].slice(0, 30);
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
      setJobs((prev: ParseJob[]): ParseJob[] => {
        const nextJobs: ParseJob[] = prev.map((job): ParseJob => {
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
      // Вызываем API для удаления флага отмены (опционально)
      await deleteCeleryTask(jobId);
      await deleteSharedParseJob(jobId).catch(() => null);
      setJobs((prev: ParseJob[]): ParseJob[] => {
        const nextJobs: ParseJob[] = prev.filter((job) => job.jobId !== jobId);
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
        <h2>Главная</h2>
        <div className="actions">
          <button className="btn btn-primary" onClick={startParsing}>
            Запустить парсинг статей
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Параметры парсинга</h3>
        <div className="filters">
          <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поисковый запрос" />
          <select value={source} onChange={(e) => setSource(e.target.value as PaperSource | "all")}>
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
        <article className="panel kpi-card">
          <h3>С эмбеддингами</h3>
          <p className="kpi">{summary?.papers_with_embedding || 0}</p>
        </article>
        <article className="panel kpi-card">
          <h3>Покрытие эмбеддингами</h3>
          <p className="kpi">{summary?.embedding_coverage || 0}%</p>
        </article>
        <article className="panel kpi-card">
          <h3>Полнота данных</h3>
          <p className="kpi">{avgCompleteness}%</p>
        </article>
        <article className="panel kpi-card">
          <h3>Среднее качество</h3>
          <p className="kpi">{summary?.avg_quality_score || 0}</p>
        </article>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: 16 }}>
        <article className="panel">
          <h3>Тренд публикаций (по месяцам)</h3>
          {trend.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={trend}>
                <XAxis dataKey="period" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="count" stroke="#4a6cf7" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">Нет данных</p>
          )}
        </article>
        <article className="panel">
          <h3>Распределение по источникам</h3>
          {sourcePieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={sourcePieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                  {sourcePieData.map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">Нет данных</p>
          )}
        </article>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: 16 }}>
        <article className="panel">
          <h3>Топ журналов</h3>
          {topJournals.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={topJournals}>
                <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={80} />
                <YAxis />
                <Tooltip />
                <Bar dataKey="count" fill="#4a6cf7" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">Нет данных</p>
          )}
        </article>
        <article className="panel">
          <h3>Полнота данных</h3>
          {qualityData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={qualityData} layout="vertical">
                <XAxis type="number" domain={[0, 100]} />
                <YAxis dataKey="name" type="category" width={100} />
                <Tooltip formatter={(value: number) => `${value.toFixed(1)}%`} />
                <Bar dataKey="percent" fill="#00c49f" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">Нет данных</p>
          )}
        </article>
      </div>

      <div className="panel">
        <h3>Топ авторов</h3>
        {topAuthors.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Автор</th>
                <th>Количество статей</th>
              </tr>
            </thead>
            <tbody>
              {topAuthors.map((author, idx) => (
                <tr key={idx}>
                  <td>{idx + 1}</td>
                  <td>{author.name}</td>
                  <td>{author.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Нет данных</p>
        )}
      </div>

      <div className="panel">
        <h3>Топ ключевых слов</h3>
        {topKeywords.length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {topKeywords.map((item, idx) => (
              <span
                key={idx}
                style={{
                  padding: "6px 12px",
                  background: `rgba(74, 108, 247, ${0.1 + (idx / topKeywords.length) * 0.4})`,
                  borderRadius: 16,
                  fontSize: 14,
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                }}
              >
                {item.name} <strong style={{ marginLeft: 4 }}>{item.count}</strong>
              </span>
            ))}
          </div>
        ) : (
          <p className="muted">Нет данных</p>
        )}
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
        <h3>Текущие парсинг-задачи</h3>
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
                <th>Прогресс</th>
                <th>Сохранено</th>
                <th>Действия</th>
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
                  const expectedDelta = 50;
                  return Math.min(100, Math.round((delta / expectedDelta) * 100));
                })();

                const statusText = (() => {
                  if (j.status === "completed") return "✓ Завершено";
                  if (j.status === "cancelled") return "Отменено";

                  if (j.celeryStatus) {
                    const status = j.celeryStatus.status;
                    if (status === "SUCCESS") return "✓ Завершено";
                    if (status === "FAILURE") return "✕ Ошибка";
                    if (status === "REVOKED") return "Отменено";
                    if (status === "PENDING") return "Ожидание...";
                    if (status === "STARTED") return j.celeryStatus.result?.status || "В процессе...";
                    if (status === "RETRY") return "Повтор...";
                  }
                  return "В обработке";
                })();

                const savedCount =
                  j.celeryStatus?.saved_count ||
                  j.celeryStatus?.result?.saved_count ||
                  j.lastObservedCount - j.initialCount;

                return (
                  <tr key={j.jobId}>
                    <td style={{ wordBreak: "break-word", fontFamily: "monospace", fontSize: "0.85em" }}>
                      {j.jobId}
                    </td>
                    <td>{j.source}</td>
                    <td style={{ maxWidth: 280 }}>{j.query}</td>
                    <td>
                      <span
                        className={`status ${
                          j.status === "completed" || j.celeryStatus?.status === "SUCCESS" ? "active" : ""
                        }`}
                      >
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
      </div>
    </div>
  );
}
