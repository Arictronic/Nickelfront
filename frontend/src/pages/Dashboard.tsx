import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getCeleryTaskStatus,
  getPapersCount,
  getRecentPapers,
  parseAll,
  parsePapers,
  revokeCeleryTask,
  deleteCeleryTask,
  deleteSharedParseJob,
} from "../api/papers";
import { apiClient } from "../api/client";
import { getDashboardJobs, getDashboardOverview, triggerDashboardAction } from "../api/dashboard";
import { getSystemSettings } from "../api/settings";
import ActiveJobsPanel from "../components/dashboard/ActiveJobsPanel";
import DashboardHeader from "../components/dashboard/DashboardHeader";
import DashboardKpiGrid from "../components/dashboard/DashboardKpiGrid";
import DashboardMiniAnalytics, { type TopItem, type TrendData } from "../components/dashboard/DashboardMiniAnalytics";
import DiagnosticsPanel from "../components/dashboard/DiagnosticsPanel";
import ParserLaunchPanel, { type SourceGuidance } from "../components/dashboard/ParserLaunchPanel";
import PipelineReadinessPanel from "../components/dashboard/PipelineReadinessPanel";
import QuickActionsPanel from "../components/dashboard/QuickActionsPanel";
import RecentPapersPanel from "../components/dashboard/RecentPapersPanel";
import SourceBoard from "../components/dashboard/SourceBoard";
import SystemHealthStrip from "../components/dashboard/SystemHealthStrip";
import { PAPER_SOURCES, type Paper, type PaperSource, type PdfProcessingMode } from "../types/paper";
import { useAuthStore } from "../store/authStore";
import type { DashboardActionName, DashboardActionPayload, DashboardLoadError, DashboardOverview, DashboardSourceStatus } from "../types/dashboard";
import type { ParserSettings } from "../types/settings";
import {
  buildUpdatedJobFromCelery,
  clearParseJobStorage,
  isExpiredPendingTask,
  loadJobs,
  mergeJobs,
  normalizeJobs,
  saveJobs,
  type ParseJob,
} from "../utils/parseJobs";

const RECENT_PAPERS_LIMIT = 12;

const SOURCE_GUIDANCE: Record<PaperSource | "all", SourceGuidance> = {
  all: { method: "API", short: "Запускает сбор по всем включённым источникам. Лимит применяется отдельно к каждому источнику." },
  CORE: { method: "API", short: "CORE хорошо подходит для open-access работ и PDF, но качество метаданных зависит от внешних репозиториев." },
  arXiv: { method: "API", short: "Препринты с хорошей доступностью PDF; лучший быстрый источник для англоязычных материаловедческих запросов." },
  OpenAlex: { method: "API", short: "Широкий индекс метаданных и ссылок; полный текст/PDF часто требуют последующей загрузки с внешних сайтов." },
  Crossref: { method: "API", short: "Сильный источник DOI и библиографии. Полный текст обычно не гарантирован." },
  EuropePMC: { method: "API", short: "Полезен для материалов на стыке материаловедения, химии и биомедицины." },
  CyberLeninka: { method: "HTML", short: "Русскоязычные публикации. Возможны изменения HTML, 403/captcha и неполный полный текст." },
  eLibrary: { method: "HTML", short: "Русскоязычные карточки публикаций. Доступность текста зависит от сессии и ограничений сайта." },
  Rospatent: { method: "HTML", short: "Патентные документы РФ. Лучше работает по патентным терминам, номерам и формулировкам изобретений." },
  FreePatent: { method: "HTML", short: "Публичные патентные карточки. Структура страниц может меняться, поэтому важна диагностика ошибок." },
  GooglePatents: { method: "HTML", short: "Удобен для патентного поиска по теме, номеру публикации или прямой ссылке." },
  PATENTSCOPE: { method: "HTML", short: "Международные патентные публикации WIPO; возможны медленные ответы и ограничения выдачи." },
};

const EMPTY_OVERVIEW: DashboardOverview = {
  generatedAt: new Date().toISOString(),
  counts: {
    totalPapers: 0,
    todayPapers: 0,
    withAbstract: 0,
    withFullText: 0,
    withPdf: 0,
    withEmbeddings: 0,
    ragReady: 0,
    metadataReady: 0,
    qwenReady: 0,
    withContentParts: 0,
    contentReady: 0,
    ragCandidates: 0,
    vectorIndexed: 0,
    vectorIndexRecords: 0,
    ragIndexed: 0,
    processingErrors: 0,
    contentQueued: 0,
  },
  pipeline: {
    metadataPercent: 0,
    abstractPercent: 0,
    fullTextPercent: 0,
    pdfPercent: 0,
    contentPartsPercent: 0,
    contentReadyPercent: 0,
    embeddingPercent: 0,
    vectorPercent: 0,
    ragPercent: 0,
    qwenPercent: 0,
    qualityPercent: 0,
  },
  services: {},
  jobs: { active: 0, queued: 0, failedRecent: 0 },
  sources: [],
  diagnostics: [],
  recommendedActions: [],
};

function normalizeParseLimit(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.min(100, Math.floor(parsed)));
}

function extractErrorMessage(error: unknown): string {
  if (!error) return "Неизвестная ошибка";
  const maybe = error as { message?: string; response?: { data?: { detail?: unknown; message?: unknown; error?: unknown; details?: unknown } } };
  const detail = maybe.response?.data?.detail ?? maybe.response?.data?.message ?? maybe.response?.data?.error ?? maybe.response?.data?.details;
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

function buildFallbackSources(parserSettings: ParserSettings | null): DashboardSourceStatus[] {
  const enabledFlags = parserSettings?.enabled_sources ?? {};
  const sourceLimits = parserSettings?.source_limits ?? {};
  const maxLimit = parserSettings?.max_limit ?? 100;
  return PAPER_SOURCES.map((source) => ({
    name: source,
    kind: SOURCE_GUIDANCE[source].method,
    enabled: enabledFlags[source] !== false,
    limit: sourceLimits[source] ?? maxLimit,
    papersCount: 0,
    addedToday: 0,
    withFullText: 0,
    withEmbeddings: 0,
    errors: 0,
    successRate: null,
    errorRate: null,
    lastDurationSec: null,
    lastStatus: null,
    lastError: null,
    lastRunAt: null,
  }));
}

export default function Dashboard() {
  const [overview, setOverview] = useState<DashboardOverview>(EMPTY_OVERVIEW);
  const [latest, setLatest] = useState<Paper[]>([]);
  const [jobs, setJobs] = useState<ParseJob[]>(() => loadJobs());
  const [trend, setTrend] = useState<TrendData[]>([]);
  const [topKeywords, setTopKeywords] = useState<TopItem[]>([]);
  const [parserSettings, setParserSettings] = useState<ParserSettings | null>(null);
  const [loadErrors, setLoadErrors] = useState<DashboardLoadError[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [query, setQuery] = useState("nickel-based superalloys");
  const [source, setSource] = useState<PaperSource | "all">("arXiv");
  const [limit, setLimit] = useState(25);
  const [pdfMode, setPdfMode] = useState<PdfProcessingMode>("auto");
  const [parsingError, setParsingError] = useState<string | null>(null);
  const [startingParse, setStartingParse] = useState(false);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const isAdmin = !!useAuthStore((state) => state.user?.is_admin);
  const jobsRef = useRef<ParseJob[]>(jobs);
  const pollingRef = useRef(false);

  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  const enabledSources = useMemo(() => {
    const flags = parserSettings?.enabled_sources ?? {};
    return PAPER_SOURCES.filter((src) => flags[src] !== false);
  }, [parserSettings]);

  const selectedSourceDisabled = source !== "all" && parserSettings?.enabled_sources?.[source] === false;
  const sourceLimit = source === "all"
    ? Math.min(...enabledSources.map((src) => parserSettings?.source_limits?.[src] ?? parserSettings?.max_limit ?? 100), parserSettings?.max_limit ?? 100)
    : parserSettings?.source_limits?.[source] ?? parserSettings?.max_limit ?? 100;

  const dashboardSources = useMemo(() => {
    if (overview.sources.length > 0) return overview.sources;
    return buildFallbackSources(parserSettings);
  }, [overview.sources, parserSettings]);

  const fetchPage = useCallback(async (options: { forceRefresh?: boolean } = {}) => {
    const [overviewRes, latestRes, trendRes, keywordsRes, settingsRes] = await Promise.allSettled([
      getDashboardOverview({ forceRefresh: options.forceRefresh }),
      getRecentPapers({ limit: RECENT_PAPERS_LIMIT, source: "all" }),
      apiClient.get<{ trend: TrendData[] }>("/analytics/metrics/trend?group_by=month&limit=12"),
      apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=keywords&limit=12"),
      getSystemSettings(),
    ]);

    if (overviewRes.status === "fulfilled") setOverview(overviewRes.value);
    setLatest(latestRes.status === "fulfilled" ? latestRes.value : []);
    setTrend(trendRes.status === "fulfilled" ? trendRes.value.data?.trend ?? [] : []);
    setTopKeywords(keywordsRes.status === "fulfilled" ? keywordsRes.value.data?.items ?? [] : []);
    if (settingsRes.status === "fulfilled") setParserSettings(settingsRes.value.settings.parser);

    const errors = [
      resultError(overviewRes, "dashboard-overview", "Сводка dashboard"),
      resultError(latestRes, "recent-papers", "Последние документы"),
      resultError(trendRes, "trend", "Тренд публикаций"),
      resultError(keywordsRes, "keywords", "Ключевые слова"),
      resultError(settingsRes, "settings", "Технические настройки"),
    ].filter(Boolean) as DashboardLoadError[];
    setLoadErrors(errors);
  }, []);

  const refreshSharedJobs = useCallback(async () => {
    const [countRes, dashboardJobsRes] = await Promise.allSettled([getPapersCount("all"), getDashboardJobs(50)]);
    const total = countRes.status === "fulfilled" ? countRes.value : null;
    const dashboardJobs = dashboardJobsRes.status === "fulfilled" ? normalizeJobs(dashboardJobsRes.value.jobs) : [];

    if (total === 0 && dashboardJobs.length === 0) {
      clearParseJobStorage();
      jobsRef.current = [];
      setJobs([]);
      return;
    }

    setJobs((current) => {
      const merged = mergeJobs(current, dashboardJobs);
      jobsRef.current = merged;
      saveJobs(merged);
      return merged;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setRefreshing(true);
    Promise.allSettled([fetchPage(), refreshSharedJobs()])
      .catch((error) => {
        if (!cancelled) setLoadErrors([{ key: "dashboard", label: "Главная", message: extractErrorMessage(error) }]);
      })
      .finally(() => {
        if (!cancelled) {
          setRefreshing(false);
          setInitialLoading(false);
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
        if (hasNewlyFinishedJobs) await fetchPage({ forceRefresh: true }).catch(() => null);
      } finally {
        pollingRef.current = false;
      }
    }, 5000);

    return () => window.clearInterval(interval);
  }, [fetchPage, refreshJobs]);

  const startParsing = async (sourceOverride?: PaperSource | "all") => {
    if (startingParse) return;
    setParsingError(null);
    const selectedSource = sourceOverride ?? source;
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      setParsingError("Поле поискового запроса обязательно");
      return;
    }
    if (parserSettings?.enabled === false) {
      setParsingError("Парсинг отключён в технических настройках");
      return;
    }
    if (selectedSource !== "all" && parserSettings?.enabled_sources?.[selectedSource] === false) {
      setParsingError(`Источник ${selectedSource} отключён в технических настройках`);
      return;
    }
    if (selectedSource === "all") {
      const ok = window.confirm(`Запустить парсинг по всем включённым источникам (${enabledSources.length})? Лимит ${limit} будет применён на каждый источник.`);
      if (!ok) return;
    }

    setStartingParse(true);
    try {
      const selectedLimit = selectedSource === "all"
        ? Math.min(...enabledSources.map((src) => parserSettings?.source_limits?.[src] ?? parserSettings?.max_limit ?? 100), parserSettings?.max_limit ?? 100)
        : parserSettings?.source_limits?.[selectedSource] ?? parserSettings?.max_limit ?? 100;
      const normalizedLimit = normalizeParseLimit(Math.min(limit, selectedLimit || 100));
      setLimit(normalizedLimit);
      setSource(selectedSource);
      const currentCount = await getPapersCount(selectedSource);
      let job: ParseJob;
      if (selectedSource === "all") {
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
        const res = await parsePapers({ query: normalizedQuery, limit: normalizedLimit, source: selectedSource, pdfMode });
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
    setRefreshing(true);
    await Promise.allSettled([fetchPage({ forceRefresh: true }), refreshSharedJobs(), refreshJobs()]);
    setRefreshing(false);
  };

  const runDashboardAction = async (action: DashboardActionName, payload: DashboardActionPayload = {}) => {
    if (runningAction) return;
    setRunningAction(action);
    setActionStatus(null);
    setActionError(null);
    try {
      const result = await triggerDashboardAction(action, payload);
      setActionStatus(`${result.title}: задача поставлена в очередь (${result.taskId.slice(0, 8)})`);
      await Promise.allSettled([fetchPage({ forceRefresh: true }), refreshSharedJobs()]);
    } catch (error) {
      setActionError(extractErrorMessage(error));
    } finally {
      setRunningAction(null);
    }
  };

  if (initialLoading) {
    return (
      <div className="page dashboard-page dashboard-redesign-page">
        <DashboardHeader generatedAt={overview.generatedAt} onRefresh={refreshDashboard} refreshing={refreshing} />
        <section className="panel dashboard-loading-panel">
          <span className="eyebrow">Загрузка</span>
          <h3>Загрузка dashboard…</h3>
          <p>Получаю сводку backend, последние документы, задачи и состояние сервисов.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="page dashboard-page dashboard-redesign-page">
      <DashboardHeader generatedAt={overview.generatedAt} onRefresh={refreshDashboard} refreshing={refreshing} />
      <SystemHealthStrip services={overview.services} />

      <div className="dashboard-command-grid">
        <ParserLaunchPanel
          query={query}
          source={source}
          limit={limit}
          pdfMode={pdfMode}
          sources={PAPER_SOURCES}
          enabledSources={enabledSources}
          parserSettings={parserSettings}
          sourceGuidance={SOURCE_GUIDANCE}
          selectedSourceDisabled={selectedSourceDisabled}
          sourceLimit={sourceLimit}
          startingParse={startingParse}
          error={parsingError}
          onQueryChange={setQuery}
          onSourceChange={setSource}
          onLimitChange={setLimit}
          onPdfModeChange={setPdfMode}
          onStart={() => startParsing()}
        />
        <QuickActionsPanel
          recommendedActions={overview.recommendedActions}
          isAdmin={isAdmin}
          runningAction={runningAction}
          actionStatus={actionStatus}
          actionError={actionError}
          onRunAction={runDashboardAction}
        />
      </div>

      <DashboardKpiGrid counts={overview.counts} pipeline={overview.pipeline} jobs={overview.jobs} />

      <div className="dashboard-main-grid">
        <ActiveJobsPanel
          jobs={jobs}
          expandedJobId={expandedJobId}
          onToggle={(jobId) => setExpandedJobId((current) => current === jobId ? null : jobId)}
          onCancel={cancelJob}
          onDelete={deleteJob}
        />
        <PipelineReadinessPanel counts={overview.counts} pipeline={overview.pipeline} />
      </div>

      <SourceBoard sources={dashboardSources} />

      <div className="dashboard-main-grid dashboard-lower-grid">
        <RecentPapersPanel papers={latest} isAdmin={isAdmin} />
        <DiagnosticsPanel diagnostics={overview.diagnostics} loadErrors={loadErrors} />
      </div>

      <DashboardMiniAnalytics trend={trend} keywords={topKeywords} sources={dashboardSources} />
    </div>
  );
}
