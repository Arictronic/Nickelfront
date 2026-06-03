import { apiClient } from "./client";
import type {
  DashboardCounts,
  DashboardDiagnostic,
  DashboardJobsResponse,
  DashboardOverview,
  DashboardPipeline,
  DashboardActionPayload,
  DashboardActionResult,
  DashboardRecommendedAction,
  DashboardServiceStatus,
  DashboardSourceStatus,
} from "../types/dashboard";
import type { CeleryTaskStatus } from "./papers";
import type { ParseJob, ParseJobStatus } from "../utils/parseJobs";

type ApiCounts = {
  total_papers?: number;
  today_papers?: number;
  with_abstract?: number;
  with_full_text?: number;
  with_pdf?: number;
  with_embeddings?: number;
  rag_ready?: number;
  metadata_ready?: number;
  qwen_ready?: number;
  with_content_parts?: number;
  content_ready?: number;
  rag_candidates?: number;
  vector_indexed?: number;
  vector_index_records?: number;
  rag_indexed?: number;
  vector_ids_status?: "verified" | "unknown";
  rag_ids_status?: "verified" | "unknown";
  processing_errors?: number;
  content_queued?: number;
};

type ApiPipeline = {
  metadata_percent?: number;
  abstract_percent?: number;
  full_text_percent?: number;
  pdf_percent?: number;
  content_parts_percent?: number;
  content_ready_percent?: number;
  embedding_percent?: number;
  vector_percent?: number;
  rag_percent?: number;
  qwen_percent?: number;
  quality_percent?: number;
};

type ApiSourceStatus = {
  name?: string;
  kind?: string;
  enabled?: boolean;
  limit?: number;
  papers_count?: number;
  added_today?: number;
  with_full_text?: number;
  with_embeddings?: number;
  errors?: number;
  success_rate?: number | null;
  error_rate?: number | null;
  last_duration_sec?: number | null;
  last_status?: string | null;
  last_error?: string | null;
  last_run_at?: number | string | null;
};

type ApiDiagnostic = {
  level?: string;
  title?: string;
  message?: string;
  action_label?: string | null;
  action_to?: string | null;
};

type ApiRecommendedAction = {
  kind?: string;
  title?: string;
  description?: string;
  action_label?: string | null;
  action_to?: string | null;
  action_name?: string | null;
  action_payload?: DashboardActionPayload | null;
};

type ApiDashboardJob = {
  job_id?: string;
  jobId?: string;
  source?: string;
  query?: string;
  status?: string;
  job_type?: string;
  jobType?: string;
  celery_status?: Record<string, unknown>;
  progress_percent?: number;
  saved?: number;
  updated?: number;
  duplicates?: number;
  content_queued?: number;
  content_skipped?: number;
  current?: number;
  total?: number;
  stage?: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_sec?: number;
  error?: string | null;
  startedAt?: number;
  initialCount?: number;
  lastObservedCount?: number;
  lastCountChangeAt?: number;
  savedCount?: number;
  updatedCount?: number;
  duplicateCount?: number;
  contentQueuedCount?: number;
  contentSkippedCount?: number;
  lastPolledAt?: number | null;
};

type ApiJobsResponse = {
  jobs?: ApiDashboardJob[];
  summary?: {
    active?: number;
    queued?: number;
    failed_recent?: number;
  };
};

type ApiOverview = {
  generated_at?: string;
  counts?: ApiCounts;
  pipeline?: ApiPipeline;
  services?: Record<string, DashboardServiceStatus>;
  jobs?: {
    active?: number;
    queued?: number;
    failed_recent?: number;
  };
  sources?: ApiSourceStatus[];
  diagnostics?: ApiDiagnostic[];
  recommended_actions?: ApiRecommendedAction[];
};

function numberOrZero(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function mapCounts(counts: ApiCounts | undefined): DashboardCounts {
  return {
    totalPapers: numberOrZero(counts?.total_papers),
    todayPapers: numberOrZero(counts?.today_papers),
    withAbstract: numberOrZero(counts?.with_abstract),
    withFullText: numberOrZero(counts?.with_full_text),
    withPdf: numberOrZero(counts?.with_pdf),
    withEmbeddings: numberOrZero(counts?.with_embeddings),
    ragReady: numberOrZero(counts?.rag_ready),
    metadataReady: numberOrZero(counts?.metadata_ready),
    qwenReady: numberOrZero(counts?.qwen_ready),
    withContentParts: numberOrZero(counts?.with_content_parts),
    contentReady: numberOrZero(counts?.content_ready),
    ragCandidates: numberOrZero(counts?.rag_candidates),
    vectorIndexed: numberOrZero(counts?.vector_indexed),
    vectorIndexRecords: numberOrZero(counts?.vector_index_records),
    ragIndexed: numberOrZero(counts?.rag_indexed),
    vectorIdsStatus: counts?.vector_ids_status === "unknown" ? "unknown" : "verified",
    ragIdsStatus: counts?.rag_ids_status === "unknown" ? "unknown" : "verified",
    processingErrors: numberOrZero(counts?.processing_errors),
    contentQueued: numberOrZero(counts?.content_queued),
  };
}

function mapPipeline(pipeline: ApiPipeline | undefined): DashboardPipeline {
  return {
    metadataPercent: numberOrZero(pipeline?.metadata_percent),
    abstractPercent: numberOrZero(pipeline?.abstract_percent),
    fullTextPercent: numberOrZero(pipeline?.full_text_percent),
    pdfPercent: numberOrZero(pipeline?.pdf_percent),
    contentPartsPercent: numberOrZero(pipeline?.content_parts_percent),
    contentReadyPercent: numberOrZero(pipeline?.content_ready_percent),
    embeddingPercent: numberOrZero(pipeline?.embedding_percent),
    vectorPercent: numberOrZero(pipeline?.vector_percent),
    ragPercent: numberOrZero(pipeline?.rag_percent),
    qwenPercent: numberOrZero(pipeline?.qwen_percent),
    qualityPercent: numberOrZero(pipeline?.quality_percent),
  };
}

function mapSource(source: ApiSourceStatus): DashboardSourceStatus {
  return {
    name: source.name || "unknown",
    kind: source.kind || "unknown",
    enabled: source.enabled !== false,
    limit: numberOrZero(source.limit),
    papersCount: numberOrZero(source.papers_count),
    addedToday: numberOrZero(source.added_today),
    withFullText: numberOrZero(source.with_full_text),
    withEmbeddings: numberOrZero(source.with_embeddings),
    errors: numberOrZero(source.errors),
    successRate: nullableNumber(source.success_rate),
    errorRate: nullableNumber(source.error_rate),
    lastDurationSec: nullableNumber(source.last_duration_sec),
    lastStatus: source.last_status ?? null,
    lastError: source.last_error ?? null,
    lastRunAt: source.last_run_at ?? null,
  };
}

function mapDiagnostic(item: ApiDiagnostic): DashboardDiagnostic {
  const level = ["success", "info", "warning", "error"].includes(String(item.level))
    ? (String(item.level) as DashboardDiagnostic["level"])
    : "info";
  return {
    level,
    title: item.title || "Диагностика",
    message: item.message || "Нет подробностей",
    actionLabel: item.action_label ?? null,
    actionTo: item.action_to ?? null,
  };
}

function mapRecommendedAction(item: ApiRecommendedAction): DashboardRecommendedAction {
  const kind = ["success", "info", "warning", "error"].includes(String(item.kind))
    ? (String(item.kind) as DashboardRecommendedAction["kind"])
    : "info";
  return {
    kind,
    title: item.title || "Действие",
    description: item.description || "Нет подробностей",
    actionLabel: item.action_label || "Открыть",
    actionTo: item.action_to || "/dashboard",
    actionName: item.action_name as DashboardRecommendedAction["actionName"] || null,
    actionPayload: item.action_payload || null,
  };
}

function isPlaceholderJobId(jobId: string): boolean {
  return /^(test|mock|demo|sample)[-_]/i.test(jobId.trim());
}

function normalizeParseJobStatus(value: unknown): ParseJobStatus {
  const status = String(value || "").trim();
  if (["completed_with_errors", "partial_success", "warning"].includes(status)) return "partial";
  return ["in_progress", "completed", "partial", "cancelled", "failed", "expired"].includes(status)
    ? (status as ParseJobStatus)
    : "in_progress";
}

function normalizeCeleryStatus(value: unknown): CeleryTaskStatus["status"] {
  const status = String(value || "").trim().toUpperCase();
  const allowed: CeleryTaskStatus["status"][] = ["PENDING", "RECEIVED", "STARTED", "PROGRESS", "RETRY", "FAILURE", "SUCCESS", "REVOKED", "UNKNOWN"];
  return allowed.includes(status as CeleryTaskStatus["status"]) ? (status as CeleryTaskStatus["status"]) : "UNKNOWN";
}

function mapDashboardJob(job: ApiDashboardJob): ParseJob {
  const jobId = String(job.jobId || job.job_id || "");
  const startedAt = numberOrZero(job.startedAt) || Date.now();
  const progress = numberOrZero(job.progress_percent);
  const current = numberOrZero(job.current);
  const total = numberOrZero(job.total);
  const result: Record<string, unknown> = {
    ...((job.celery_status?.result as Record<string, unknown> | undefined) || {}),
    progress_percent: progress,
    current,
    total,
    stage_label: job.stage || job.celery_status?.stage_label,
    elapsed_seconds: numberOrZero(job.duration_sec),
    saved_count: numberOrZero(job.saved ?? job.savedCount),
    updated_count: numberOrZero(job.updated ?? job.updatedCount),
    duplicate_count: numberOrZero(job.duplicates ?? job.duplicateCount),
    content_queued_count: numberOrZero(job.content_queued ?? job.contentQueuedCount),
    content_skipped_count: numberOrZero(job.content_skipped ?? job.contentSkippedCount),
    error: job.error ?? job.celery_status?.error,
  };

  return {
    jobId,
    startedAt,
    query: String(job.query || ""),
    source: String(job.source || "all"),
    jobType: String(job.jobType || job.job_type || job.celery_status?.job_type || job.celery_status?.dashboard_action || "parse"),
    initialCount: numberOrZero(job.initialCount),
    lastObservedCount: numberOrZero(job.lastObservedCount ?? job.initialCount),
    lastCountChangeAt: numberOrZero(job.lastCountChangeAt) || startedAt,
    status: normalizeParseJobStatus(job.status),
    celeryStatus: {
      ...(job.celery_status || {}),
      task_id: jobId,
      status: normalizeCeleryStatus(job.celery_status?.status || job.celery_status?.state),
      result,
      progress: result,
      current,
      total,
      saved_count: result.saved_count as number,
      updated_count: result.updated_count as number,
      duplicate_count: result.duplicate_count as number,
      content_queued_count: result.content_queued_count as number,
      content_skipped_count: result.content_skipped_count as number,
    },
    lastPolledAt: nullableNumber(job.lastPolledAt) ?? undefined,
    savedCount: numberOrZero(job.savedCount ?? job.saved),
    updatedCount: numberOrZero(job.updatedCount ?? job.updated),
    duplicateCount: numberOrZero(job.duplicateCount ?? job.duplicates),
    contentQueuedCount: numberOrZero(job.contentQueuedCount ?? job.content_queued),
    contentSkippedCount: numberOrZero(job.contentSkippedCount ?? job.content_skipped),
  };
}

export async function getDashboardOverview(options: { forceRefresh?: boolean } = {}): Promise<DashboardOverview> {
  const { data } = await apiClient.get<ApiOverview>("/dashboard/overview", {
    params: {
      timezone_offset_minutes: -new Date().getTimezoneOffset(),
      force_refresh: options.forceRefresh || undefined,
    },
  });

  return {
    generatedAt: data.generated_at || new Date().toISOString(),
    counts: mapCounts(data.counts),
    pipeline: mapPipeline(data.pipeline),
    services: data.services || {},
    jobs: {
      active: numberOrZero(data.jobs?.active),
      queued: numberOrZero(data.jobs?.queued),
      failedRecent: numberOrZero(data.jobs?.failed_recent),
    },
    sources: (data.sources || []).map(mapSource),
    diagnostics: (data.diagnostics || []).map(mapDiagnostic),
    recommendedActions: (data.recommended_actions || []).map(mapRecommendedAction),
  };
}

export async function getDashboardJobs(limit = 20): Promise<DashboardJobsResponse> {
  const { data } = await apiClient.get<ApiJobsResponse>("/dashboard/jobs", { params: { limit } });
  return {
    jobs: (data.jobs || []).map(mapDashboardJob).filter((job) => job.jobId && !isPlaceholderJobId(job.jobId)),
    summary: {
      active: numberOrZero(data.summary?.active),
      queued: numberOrZero(data.summary?.queued),
      failedRecent: numberOrZero(data.summary?.failed_recent),
    },
  };
}


export async function triggerDashboardAction(
  action: string,
  payload: DashboardActionPayload = {},
): Promise<DashboardActionResult> {
  const { data } = await apiClient.post<{
    action?: string;
    title?: string;
    task_id?: string;
    status?: string;
    source?: string | null;
    query?: string | null;
    job_type?: string | null;
    parse_admission?: Record<string, unknown> | null;
  }>(`/dashboard/actions/${encodeURIComponent(action)}`, payload);

  return {
    action: data.action || action,
    title: data.title || "Действие dashboard",
    taskId: String(data.task_id || ""),
    status: data.status || "queued",
    source: data.source ?? null,
    query: data.query ?? null,
    jobType: data.job_type ?? null,
    parseAdmission: data.parse_admission ?? null,
  };
}
