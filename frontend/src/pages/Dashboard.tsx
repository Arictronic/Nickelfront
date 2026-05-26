import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, PieChart, Pie, Cell, LineChart, Line, ResponsiveContainer, Legend } from "recharts";
import {
  getPapersCount,
  getRecentPapers,
  getCeleryTaskStatus,
  getSharedParseJobs,
  parseAll,
  parsePapers,
  revokeCeleryTask,
  deleteCeleryTask,
  deleteSharedParseJob,
} from "../api/papers";
import { PAPER_SOURCES, Paper, PaperSource, PdfProcessingMode } from "../types/paper";
import type { ParserSettings } from "../types/settings";
import { Link } from "react-router-dom";
import { apiClient } from "../api/client";
import { getSystemSettings } from "../api/settings";
import {
  buildUpdatedJobFromCelery,
  clearParseJobStorage,
  getCeleryStatusMeta,
  getParseJobProgressPercent,
  getParseJobSavedCount,
  getParseJobStatusClass,
  getParseJobStatusText,
  isExpiredPendingTask,
  loadJobs,
  mergeJobs,
  normalizeJobs,
  saveJobs,
  type ParseJob,
} from "../utils/parseJobs";

const COLORS = ["#4a6cf7", "#00c49f", "#ffbb28", "#ff8042", "#8884d8"];
const RECENT_PAPERS_LIMIT = 20;

const COMPLETENESS_LABELS_RU: Record<string, string> = {
  with_abstract: "Аннотация",
  with_full_text: "Полный текст",
  with_keywords: "Ключевые слова",
  with_doi: "DOI",
  with_authors: "Авторы",
  with_embedding: "Эмбеддинг",
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

type SourceGuidance = {
  method: "API" | "HTML";
  short: string;
};

type DashboardLoadError = {
  key: string;
  label: string;
  message: string;
};

const SOURCE_GUIDANCE: Record<PaperSource | "all", SourceGuidance> = {
  all: { method: "API", short: "Запускает парсинг по всем включённым источникам. Лимит применяется на каждый источник." },
  CORE: { method: "API", short: "Агрегатор научных работ открытого доступа; часто есть PDF и метаданные." },
  arXiv: { method: "API", short: "Препринты с хорошей доступностью PDF; лучше для англоязычных запросов." },
  OpenAlex: { method: "API", short: "Широкий индекс метаданных публикаций; полнотекст/PDF зависят от внешних хостов." },
  Crossref: { method: "API", short: "Сильный источник DOI и метаданных; полнотекст часто недоступен." },
  EuropePMC: { method: "API", short: "Биомедицинский фокус; полезен для life-science направлений." },
  CyberLeninka: { method: "HTML", short: "Русскоязычные публикации; стабильность извлечения зависит от структуры страницы." },
  eLibrary: { method: "HTML", short: "Русскоязычные библиографические карточки; полнотекст доступен не всегда." },
  Rospatent: { method: "HTML", short: "Патентные документы РФ; лучше для патентных терминов и номеров." },
  FreePatent: { method: "HTML", short: "Публичные патентные карточки; структура страниц может меняться." },
  GooglePatents: { method: "HTML", short: "Google Patents: поиск по теме, номеру публикации или прямой ссылке." },
  PATENTSCOPE: { method: "HTML", short: "Международные патентные публикации WIPO; ответы могут быть медленнее." },
};

const PDF_MODE_LABELS: Record<PdfProcessingMode, string> = {
  auto: "Авто",
  ai: "AI-анализ PDF",
};

function normalizeParseLimit(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.min(100, Math.floor(parsed)));
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function normalizeQualityReport(data: unknown): QualityReport | null {
  if (!data) return null;
  const record = asRecord(data);
  const completeness = asRecord(record.completeness ?? record.quality_metrics);
  const averages = asRecord(
    record.averages ?? {
      avg_abstract_length: 0,
      avg_keywords_count: 0,
    },
  );
  const quality_score = asRecord(record.quality_score ?? { avg: 0, min: 0, max: 0 });

  return {
    total: data.total ?? 0,
    completeness,
    averages,
    quality_score,
  };
}

function extractErrorMessage(error: unknown): string {
  if (!error) return "Неизвестная ошибка";
  const maybe = error as { message?: string; response?: { data?: { detail?: unknown; message?: unknown; error?: unknown } } };
  const detail = maybe.response?.data?.detail ?? maybe.response?.data?.message ?? maybe.response?.data?.error;
  if (typeof detail === "string") return detail;
  if (detail) return JSON.stringify(detail);
  if (maybe.message) return maybe.message;
  return String(error);
}

function resultError<T>(
  result: PromiseSettledResult<T>,
  key: string,
  label: string,
): DashboardLoadError | null {
  if (result.status === "fulfilled") return null;
  return { key, label, message: extractErrorMessage(result.reason) };
}

function getJobSourceForCount(source: ParseJob["source"]): PaperSource | "all" {
  return source === "all" ? "all" : (source as PaperSource);
}

function formatDateTime(valueMs: number) {
  return new Date(valueMs).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function Dashboard() {
  const [totalPapers, setTotalPapers] = useState(0);
  const [todayPapers, setTodayPapers] = useState(0);
  const [latest, setLatest] = useState<Paper[]>([]);
  const [jobs, setJobs] = useState<ParseJob[]>(() => loadJobs());
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [trend, setTrend] = useState<TrendData[]>([]);
  const [topJournals, setTopJournals] = useState<TopItem[]>([]);
  const [topKeywords, setTopKeywords] = useState<TopItem[]>([]);
  const [topAuthors, setTopAuthors] = useState<TopItem[]>([]);
  const [sourceDistribution, setSourceDistribution] = useState<Record<string, { count: number; percent: number }>>({});
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);
  const [parserSettings, setParserSettings] = useState<ParserSettings | null>(null);
  const [loadErrors, setLoadErrors] = useState<DashboardLoadError[]>([]);

  const [query, setQuery] = useState("nickel-based superalloys");
  const [source, setSource] = useState<PaperSource | "all">("arXiv");
  const [limit, setLimit] = useState(25);
  const [pdfMode, setPdfMode] = useState<PdfProcessingMode>("auto");
  const [parsingError, setParsingError] = useState<string | null>(null);
  const [startingParse, setStartingParse] = useState(false);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);

  const [updatedAt, setUpdatedAt] = useState(new Date());
  const jobsRef = useRef<ParseJob[]>(jobs);
  const pollingRef = useRef(false);

  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  useEffect(() => {
    const id = window.setInterval(() => setUpdatedAt(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const enabledSources = useMemo(() => {
    const flags = parserSettings?.enabled_sources ?? {};
    return PAPER_SOURCES.filter((src) => flags[src] !== false);
  }, [parserSettings]);

  const selectedSourceDisabled = source !== "all" && parserSettings?.enabled_sources?.[source] === false;
  const selectedGuidance = SOURCE_GUIDANCE[source];
  const sourceLimit = source === "all"
    ? Math.min(...enabledSources.map((src) => parserSettings?.source_limits?.[src] ?? parserSettings?.max_limit ?? 100), parserSettings?.max_limit ?? 100)
    : parserSettings?.source_limits?.[source] ?? parserSettings?.max_limit ?? 100;

  const activeJobsCount = jobs.filter((j) => j.status === "in_progress").length;
  const completedJobsCount = jobs.filter((j) => j.status === "completed").length;

  const fetchPage = useCallback(async () => {
    const [countRes, todayRes, latestRes, summaryRes, trendRes, journalsRes, keywordsRes, authorsRes, sourceRes, qualityRes, settingsRes] = await Promise.allSettled([
      getPapersCount("all"),
      apiClient.get<{ total: number }>("/analytics/metrics/daily-count", {
        params: { timezone_offset_minutes: -new Date().getTimezoneOffset() },
      }),
      getRecentPapers({ limit: RECENT_PAPERS_LIMIT, source: "all" }),
      apiClient.get<AnalyticsSummary>("/analytics/metrics/summary"),
      apiClient.get<{ trend: TrendData[] }>("/analytics/metrics/trend?group_by=month&limit=12"),
      apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=journals&limit=10"),
      apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=keywords&limit=15"),
      apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=authors&limit=10"),
      apiClient.get<{ distribution: Record<string, { count: number; percent: number }> }>("/analytics/metrics/source-distribution"),
      apiClient.get<QualityReport>("/analytics/metrics/quality-report"),
      getSystemSettings(),
    ]);

    setTotalPapers(countRes.status === "fulfilled" ? countRes.value : 0);
    setTodayPapers(todayRes.status === "fulfilled" ? todayRes.value.data?.total ?? 0 : 0);
    setLatest(latestRes.status === "fulfilled" ? latestRes.value : []);
    setSummary(summaryRes.status === "fulfilled" ? summaryRes.value.data ?? null : null);
    setTrend(trendRes.status === "fulfilled" ? trendRes.value.data?.trend ?? [] : []);
    setTopJournals(journalsRes.status === "fulfilled" ? journalsRes.value.data?.items ?? [] : []);
    setTopKeywords(keywordsRes.status === "fulfilled" ? keywordsRes.value.data?.items ?? [] : []);
    setTopAuthors(authorsRes.status === "fulfilled" ? authorsRes.value.data?.items ?? [] : []);
    setSourceDistribution(sourceRes.status === "fulfilled" ? sourceRes.value.data?.distribution ?? {} : {});
    setQualityReport(qualityRes.status === "fulfilled" ? normalizeQualityReport(qualityRes.value.data) : null);
    if (settingsRes.status === "fulfilled") {
      setParserSettings(settingsRes.value.settings.parser);
    }

    const errors = [
      resultError(countRes, "papers-count", "Количество статей"),
      resultError(todayRes, "daily-count", "Статьи за сегодня"),
      resultError(latestRes, "recent-papers", "Последние статьи"),
      resultError(summaryRes, "summary", "Сводные метрики"),
      resultError(trendRes, "trend", "Тренд публикаций"),
      resultError(journalsRes, "journals", "Топ журналов"),
      resultError(keywordsRes, "keywords", "Топ ключевых слов"),
      resultError(authorsRes, "authors", "Топ авторов"),
      resultError(sourceRes, "sources", "Распределение источников"),
      resultError(qualityRes, "quality", "Качество данных"),
      resultError(settingsRes, "settings", "Технические настройки"),
    ].filter(Boolean) as DashboardLoadError[];
    setLoadErrors(errors);
  }, []);

  const refreshSharedJobs = useCallback(async () => {
    const [countRes, sharedJobsRes] = await Promise.allSettled([getPapersCount("all"), getSharedParseJobs(50)]);
    const total = countRes.status === "fulfilled" ? countRes.value : null;
    const sharedJobs = sharedJobsRes.status === "fulfilled" ? normalizeJobs(sharedJobsRes.value) : [];

    if (total === 0 && sharedJobs.length === 0) {
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
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetchPage().catch((error) => {
      if (!cancelled) {
        setLoadErrors([{ key: "dashboard", label: "Главная", message: extractErrorMessage(error) }]);
      }
    });

    refreshSharedJobs().catch((error) => {
      if (!cancelled) {
        setLoadErrors((prev) => [
          ...prev.filter((item) => item.key !== "parse-jobs"),
          { key: "parse-jobs", label: "История задач", message: extractErrorMessage(error) },
        ]);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [fetchPage, refreshSharedJobs]);

  const refreshJobs = useCallback(async (baseJobs?: ParseJob[]) => {
    const sourceJobs = baseJobs ?? jobsRef.current;
    if (sourceJobs.length === 0) return;

    const updatedJobs = await Promise.all(
      sourceJobs.map(async (job) => {
        if (job.status !== "in_progress") return job;
        if (job.celeryStatus?.status === "REVOKED") return job;

        try {
          const celeryStatus = await getCeleryTaskStatus(job.jobId);
          const current = celeryStatus.status === "PENDING"
            ? await getPapersCount(getJobSourceForCount(job.source))
            : undefined;
          return buildUpdatedJobFromCelery(job, celeryStatus, current);
        } catch {
          const current = await getPapersCount(getJobSourceForCount(job.source));
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
      }),
    );

    jobsRef.current = updatedJobs;
    setJobs(updatedJobs);
    saveJobs(updatedJobs);
  }, []);

  useEffect(() => {
    const interval = window.setInterval(async () => {
      if (!jobsRef.current.some((job) => job.status === "in_progress") || pollingRef.current) return;
      pollingRef.current = true;
      try {
        const previousById = new Map(jobsRef.current.map((job) => [job.jobId, job.status]));
        await refreshJobs();
        const hasNewlyFinishedJobs = jobsRef.current.some((job) => {
          const previousStatus = previousById.get(job.jobId);
          return previousStatus === "in_progress" && ["completed", "cancelled", "failed", "expired"].includes(job.status);
        });
        if (hasNewlyFinishedJobs) await fetchPage().catch(() => null);
      } finally {
        pollingRef.current = false;
      }
    }, 5000);

    return () => window.clearInterval(interval);
  }, [fetchPage, refreshJobs]);

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
            name: COMPLETENESS_LABELS_RU[key] ?? key.replace("with_", "").replace(/_/g, " "),
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
    if (startingParse) return;
    setParsingError(null);
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      setParsingError("Поле поискового запроса обязательно");
      return;
    }
    if (parserSettings?.enabled === false) {
      setParsingError("Парсинг отключён в технических настройках");
      return;
    }
    if (selectedSourceDisabled) {
      setParsingError(`Источник ${source} отключён в технических настройках`);
      return;
    }
    if (source === "all") {
      const ok = window.confirm(`Запустить парсинг по всем включённым источникам (${enabledSources.length})? Лимит ${limit} будет применён на каждый источник.`);
      if (!ok) return;
    }

    setStartingParse(true);
    try {
      const normalizedLimit = normalizeParseLimit(Math.min(limit, sourceLimit || 100));
      setLimit(normalizedLimit);
      const currentCount = await getPapersCount(source);
      let job: ParseJob;
      if (source === "all") {
        const res = await parseAll({
          limitPerQuery: normalizedLimit,
          source: "all",
          query: normalizedQuery,
          pdfMode,
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
        const res = await parsePapers({ query: normalizedQuery, limit: normalizedLimit, source, pdfMode });
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

      setJobs((prev): ParseJob[] => {
        const nextJobs = mergeJobs([job, ...prev], []);
        jobsRef.current = nextJobs;
        saveJobs(nextJobs);
        return nextJobs;
      });
    } catch (e) {
      setParsingError(extractErrorMessage(e));
    } finally {
      setStartingParse(false);
    }
  };

  const cancelJob = async (jobId: string) => {
    if (!window.confirm("Остановить задачу? В очереди она будет отменена, а запущенная может не прерваться сразу.")) return;

    try {
      await revokeCeleryTask(jobId, false);
      setJobs((prev): ParseJob[] => {
        const nextJobs = prev.map((job): ParseJob =>
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
            : job,
        );
        jobsRef.current = nextJobs;
        saveJobs(nextJobs);
        return nextJobs;
      });
    } catch (e) {
      setParsingError(extractErrorMessage(e));
    }
  };

  const deleteJob = async (jobId: string) => {
    if (!window.confirm("Удалить задачу из истории? Это не повлияет на Celery, только удалит запись из интерфейса.")) return;

    try {
      await Promise.allSettled([deleteCeleryTask(jobId), deleteSharedParseJob(jobId)]);
      setJobs((prev): ParseJob[] => {
        const nextJobs = prev.filter((job) => job.jobId !== jobId);
        jobsRef.current = nextJobs;
        saveJobs(nextJobs);
        return nextJobs;
      });
    } catch (e) {
      setParsingError(extractErrorMessage(e));
    }
  };

  const refreshDashboard = async () => {
    await Promise.allSettled([fetchPage(), refreshSharedJobs(), refreshJobs()]);
    setUpdatedAt(new Date());
  };

  return (
    <div className="page dashboard-page">
      <div className="page-head">
        <h2>Главная</h2>
        <div className="actions">
          <button className="btn" onClick={refreshDashboard}>Обновить</button>
          <button className="btn btn-primary" onClick={startParsing} disabled={startingParse || selectedSourceDisabled || parserSettings?.enabled === false}>
            {startingParse ? "Запуск..." : "Запустить парсинг статей"}
          </button>
        </div>
      </div>

      {loadErrors.length > 0 && (
        <div className="panel dashboard-warning-panel">
          <h3>Часть данных не загрузилась</h3>
          <p className="muted">Главная больше не скрывает ошибки API: проверь backend, БД, миграции или авторизацию.</p>
          <ul className="dashboard-error-list">
            {loadErrors.slice(0, 6).map((item) => (
              <li key={item.key}><strong>{item.label}:</strong> {item.message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel">
        <h3>Параметры парсинга</h3>
        <div className="dashboard-parse-grid">
          <div className="filters dashboard-parse-controls">
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поисковый запрос" />
            <select value={source} onChange={(e) => setSource(e.target.value as PaperSource | "all")}>
              <option value="all" disabled={enabledSources.length === 0}>Все включённые источники</option>
              {PAPER_SOURCES.map((src) => (
                <option key={src} value={src} disabled={parserSettings?.enabled_sources?.[src] === false}>
                  {src}{parserSettings?.enabled_sources?.[src] === false ? " — отключён" : ""}
                </option>
              ))}
            </select>
            <select value={pdfMode} onChange={(e) => setPdfMode(e.target.value as PdfProcessingMode)}>
              <option value="auto">{PDF_MODE_LABELS.auto}</option>
              <option value="ai">{PDF_MODE_LABELS.ai}</option>
            </select>
            <input
              className="input dashboard-limit-input"
              type="number"
              min={1}
              max={sourceLimit || 100}
              value={limit}
              onChange={(e) => setLimit(normalizeParseLimit(e.target.value))}
            />
          </div>
          <aside className="panel dashboard-source-card">
            <div className="dashboard-source-head">
              <h4>Источник</h4>
              <span className="status neutral">{selectedGuidance.method}</span>
            </div>
            <p className="muted">{selectedGuidance.short}</p>
            <p className="muted">Режим PDF: <strong>{PDF_MODE_LABELS[pdfMode]}</strong></p>
            <p className="muted">Эффективный лимит: <strong>{Math.min(limit, sourceLimit || 100)}</strong>{source === "all" ? " на источник" : ""}</p>
            {source === "all" && <p className="muted">Будут использованы только включённые источники: {enabledSources.length || 0}.</p>}
            {selectedSourceDisabled && <p className="error">Источник отключён в технических настройках.</p>}
          </aside>
        </div>
        {parsingError && <p className="error">{parsingError}</p>}
      </div>

      <div className="kpi-grid">
        <article className="panel kpi-card"><h3>Всего статей</h3><p className="kpi">{totalPapers}</p></article>
        <article className="panel kpi-card"><h3>За сегодня</h3><p className="kpi">{todayPapers}</p></article>
        <article className="panel kpi-card"><h3>В обработке</h3><p className={`kpi-status ${activeJobsCount > 0 ? "ok" : "idle"}`}>{activeJobsCount}</p></article>
        <article className="panel kpi-card"><h3>Завершено</h3><p className="kpi">{completedJobsCount}</p></article>
        <article className="panel kpi-card"><h3>С эмбеддингами</h3><p className="kpi">{summary?.papers_with_embedding || 0}</p></article>
        <article className="panel kpi-card"><h3>Покрытие эмбеддингами</h3><p className="kpi">{summary?.embedding_coverage || 0}%</p></article>
        <article className="panel kpi-card"><h3>Полнота данных</h3><p className="kpi">{avgCompleteness}%</p></article>
        <article className="panel kpi-card"><h3>Среднее качество</h3><p className="kpi">{summary?.avg_quality_score || 0}</p></article>
      </div>

      <div className="dashboard-grid-two">
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
          ) : <p className="muted">Нет данных</p>}
        </article>
        <article className="panel">
          <h3>Распределение по источникам</h3>
          {sourcePieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={sourcePieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                  {sourcePieData.map((_, index) => <Cell key={index} fill={COLORS[index % COLORS.length]} />)}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : <p className="muted">Нет данных</p>}
        </article>
      </div>

      <div className="dashboard-grid-two">
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
          ) : <p className="muted">Нет данных</p>}
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
          ) : <p className="muted">Нет данных</p>}
        </article>
      </div>

      <div className="panel">
        <h3>Топ авторов</h3>
        {topAuthors.length > 0 ? (
          <div className="table-wrapper">
            <table className="table">
              <thead><tr><th>#</th><th>Автор</th><th>Количество статей</th></tr></thead>
              <tbody>{topAuthors.map((author, idx) => <tr key={idx}><td>{idx + 1}</td><td>{author.name}</td><td>{author.count}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <p className="muted">Нет данных</p>}
      </div>

      <div className="panel">
        <h3>Топ ключевых слов</h3>
        {topKeywords.length > 0 ? (
          <div className="dashboard-tag-cloud">
            {topKeywords.map((item, idx) => (
              <span key={idx} className="dashboard-keyword-chip">{item.name} <strong>{item.count}</strong></span>
            ))}
          </div>
        ) : <p className="muted">Нет данных</p>}
      </div>

      <div className="panel">
        <h3>Последние добавленные</h3>
        <div className="table-wrapper">
          <table className="table">
            <thead><tr><th>ID</th><th>Название</th><th>Источник</th><th>Дата</th><th>Действия</th></tr></thead>
            <tbody>
              {latest.length === 0 ? (
                <tr><td colSpan={5} className="muted">Пока нет данных. Запустите парсинг.</td></tr>
              ) : latest.slice(0, RECENT_PAPERS_LIMIT).map((p) => (
                <tr key={p.id}>
                  <td>{p.id}</td>
                  <td className="dashboard-title-cell">{p.title}</td>
                  <td>{p.source}</td>
                  <td>{p.publicationDate ? p.publicationDate.slice(0, 10) : "—"}</td>
                  <td><Link className="action-link" to={`/papers/${p.id}`}>Открыть</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">Обновлено: {updatedAt.toLocaleTimeString("ru-RU")}</p>
      </div>

      <div className="panel">
        <h3>Текущие парсинг-задачи</h3>
        {jobs.length === 0 ? <p className="muted">Задачи появятся после запуска парсинга.</p> : (
          <div className="table-wrapper">
            <table className="table">
              <thead>
                <tr><th>Celery task_id</th><th>Источник</th><th>Запрос</th><th>Статус</th><th>Прогресс</th><th>Сохранено</th><th>Действия</th></tr>
              </thead>
              <tbody>
                {jobs.slice(0, 10).map((j) => {
                  const progress = getParseJobProgressPercent(j);
                  const statusText = getParseJobStatusText(j);
                  const meta = getCeleryStatusMeta(j.celeryStatus);
                  const current = Number(j.celeryStatus?.current ?? meta.current ?? 0) || 0;
                  const total = Number(j.celeryStatus?.total ?? meta.total ?? 0) || 0;
                  const elapsed = Number(meta.elapsed_seconds ?? 0) || 0;
                  const stage = String(meta.stage_label || meta.stage || "").trim();
                  const celeryState = String(j.celeryStatus?.status || j.celeryStatus?.state || "UNKNOWN");
                  const apiStatus = String(meta.status || "").trim();
                  const errorText = String(meta.error || j.celeryStatus?.error || "").trim();
                  const isExpanded = expandedJobId === j.jobId;
                  const savedCount = getParseJobSavedCount(j);
                  const sourceDetailsRaw = asRecord(meta.sources ?? j.celeryStatus?.result?.sources_status);
                  const perSourceRows = Object.entries(sourceDetailsRaw).map(([name, value]) => {
                    const item = asRecord(value);
                    return {
                      name,
                      status: String(item.status || "unknown"),
                      saved: Number(item.saved_count || 0) || 0,
                      updated: Number(item.updated_count || 0) || 0,
                      duplicates: Number(item.duplicate_count || 0) || 0,
                      queued: Number(item.content_queued_count || 0) || 0,
                      skipped: Number(item.content_skipped_count || 0) || 0,
                      error: String(item.error || "").trim(),
                    };
                  });

                  return (
                    <Fragment key={j.jobId}>
                      <tr>
                        <td className="dashboard-task-id">{j.jobId}</td>
                        <td>{j.source}</td>
                        <td className="dashboard-query-cell">{j.query}</td>
                        <td><span className={`status ${getParseJobStatusClass(j)}`}>{statusText}</span></td>
                        <td>
                          <div className="dashboard-progress-cell">
                            <div className="dashboard-progress-track"><div className="dashboard-progress-fill" data-complete={progress === 100 ? "true" : "false"} style={{ width: `${progress}%` }} /></div>
                            <span>{progress}%</span>
                          </div>
                        </td>
                        <td>{savedCount}</td>
                        <td className="actions-inline">
                          <button className="btn" onClick={() => setExpandedJobId(isExpanded ? null : j.jobId)}>{isExpanded ? "Скрыть" : "Подробнее"}</button>
                          {j.status === "in_progress" && j.celeryStatus?.status !== "REVOKED" ? (
                            <button className="btn" onClick={() => cancelJob(j.jobId)}>Остановить</button>
                          ) : (
                            <button className="btn btn-danger" onClick={() => deleteJob(j.jobId)}>Удалить</button>
                          )}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td colSpan={7} className="dashboard-job-details">
                            <div className="dashboard-job-details-grid">
                              <div><strong>Этап:</strong> {stage || "—"}</div>
                              <div><strong>Состояние Celery:</strong> {celeryState}</div>
                              <div><strong>Статус API:</strong> {apiStatus || "—"}</div>
                              <div><strong>Счётчик:</strong> {current}/{total || "—"}</div>
                              <div><strong>Сохранено:</strong> {savedCount}</div>
                              <div><strong>Прогресс:</strong> {progress}%</div>
                              <div><strong>Запущено:</strong> {formatDateTime(j.startedAt)}</div>
                              <div><strong>Обновлено:</strong> {formatDateTime(j.lastCountChangeAt)}</div>
                              <div><strong>Длительность:</strong> {elapsed > 0 ? `${elapsed.toFixed(1)} с` : "—"}</div>
                            </div>
                            {String(j.source) === "all" && perSourceRows.length > 0 && (
                              <div className="dashboard-source-statuses">
                                <strong>Источники:</strong>
                                <div className="table-wrapper">
                                  <table className="table">
                                    <thead><tr><th>Источник</th><th>Статус</th><th>Сохранено</th><th>Обновлено</th><th>Дубликаты</th><th>В очередь</th><th>Пропущено</th><th>Ошибка</th></tr></thead>
                                    <tbody>{perSourceRows.map((row) => <tr key={`${j.jobId}:${row.name}`}><td>{row.name}</td><td>{row.status}</td><td>{row.saved}</td><td>{row.updated}</td><td>{row.duplicates}</td><td>{row.queued}</td><td>{row.skipped}</td><td className="dashboard-error-cell">{row.error || "—"}</td></tr>)}</tbody>
                                  </table>
                                </div>
                              </div>
                            )}
                            {errorText && <p className="error"><strong>Ошибка:</strong> {errorText}</p>}
                          </td>
                        </tr>
                      )}
                    </Fragment>
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
