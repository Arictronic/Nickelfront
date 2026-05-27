import type { CeleryTaskStatus, SharedParseJob } from "../api/papers";
import type { PaperSource } from "../types/paper";

export type ParseJobStatus =
  | "in_progress"
  | "completed"
  | "cancelled"
  | "failed"
  | "expired";

export type ParseJob = {
  jobId: string;
  startedAt: number;
  query: string;
  source: PaperSource | "all" | string;
  initialCount: number;
  lastObservedCount: number;
  lastCountChangeAt: number;
  status: ParseJobStatus;
  celeryStatus?: CeleryTaskStatus;
  lastPolledAt?: number;
  savedCount?: number;
  updatedCount?: number;
  duplicateCount?: number;
  contentQueuedCount?: number;
  contentSkippedCount?: number;
};

export const PARSE_JOBS_LS_KEY = "parseJobs";
const LEGACY_LS_KEYS = [
  "parseJobs.v6",
  "parseJobs.v5",
  "parseJobs.v4",
  "parseJobs.v3",
  "parseJobs.v2",
  "parseJobs.v1",
  "parseJobs.reset.v3",
];
const STALE_PENDING_TASK_MS = 30 * 60_000;
const TERMINAL_STATUSES: ParseJobStatus[] = [
  "completed",
  "cancelled",
  "failed",
  "expired",
];

function clearLegacyParseJobKeys() {
  for (const key of LEGACY_LS_KEYS) {
    localStorage.removeItem(key);
  }
}

export function clearParseJobStorage() {
  clearLegacyParseJobKeys();
  localStorage.removeItem(PARSE_JOBS_LS_KEY);
}

function isPlaceholderJobId(jobId: string): boolean {
  return /^(test|mock|demo|sample)[-_]/i.test(jobId.trim());
}

function isValidParseJob(job: unknown): job is Partial<ParseJob> {
  const maybeJob = job as Partial<ParseJob> | null | undefined;
  const jobId = typeof maybeJob?.jobId === "string" ? maybeJob.jobId.trim() : "";
  return jobId.length > 0 && !isPlaceholderJobId(jobId);
}

function toFiniteNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toNullableFiniteNumber(value: unknown): number | undefined {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function normalizeStatus(value: unknown): ParseJobStatus {
  const status = String(value || "").trim();
  return (["in_progress", ...TERMINAL_STATUSES] as string[]).includes(status)
    ? (status as ParseJobStatus)
    : "in_progress";
}

export function normalizeJobs(jobs: unknown): ParseJob[] {
  if (!Array.isArray(jobs)) return [];
  return jobs.filter(isValidParseJob).map((job) => {
    const initialCount = toFiniteNumber(job.initialCount, 0);
    const lastObservedCount = toFiniteNumber(
      job.lastObservedCount,
      initialCount,
    );
    const startedAt = toFiniteNumber(job.startedAt, Date.now());
    return {
      ...job,
      jobId: String(job.jobId),
      startedAt,
      query: String(job.query || ""),
      source: String(job.source || "all") as PaperSource | "all" | string,
      initialCount,
      lastObservedCount,
      lastCountChangeAt: toFiniteNumber(job.lastCountChangeAt, startedAt),
      status: normalizeStatus(job.status),
      savedCount: toNullableFiniteNumber(job.savedCount),
      updatedCount: toNullableFiniteNumber(job.updatedCount),
      duplicateCount: toNullableFiniteNumber(job.duplicateCount),
      contentQueuedCount: toNullableFiniteNumber(job.contentQueuedCount),
      contentSkippedCount: toNullableFiniteNumber(job.contentSkippedCount),
    };
  });
}

export function loadJobs(): ParseJob[] {
  try {
    clearLegacyParseJobKeys();
    const raw = localStorage.getItem(PARSE_JOBS_LS_KEY);
    if (!raw) return [];
    return normalizeJobs(JSON.parse(raw));
  } catch {
    clearParseJobStorage();
    return [];
  }
}

export function saveJobs(jobs: ParseJob[]) {
  localStorage.setItem(PARSE_JOBS_LS_KEY, JSON.stringify(normalizeJobs(jobs)));
}

function isTerminalStatus(status: ParseJobStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

function preferSharedJob(
  localJob: ParseJob | undefined,
  sharedJob: ParseJob,
): ParseJob {
  if (!localJob) return sharedJob;

  // Не даём старой backend-записи `in_progress` перетереть локально завершённую задачу.
  if (isTerminalStatus(localJob.status) && sharedJob.status === "in_progress") {
    return {
      ...sharedJob,
      ...localJob,
      celeryStatus: sharedJob.celeryStatus ?? localJob.celeryStatus,
      savedCount: sharedJob.savedCount ?? localJob.savedCount,
      updatedCount: sharedJob.updatedCount ?? localJob.updatedCount,
      duplicateCount: sharedJob.duplicateCount ?? localJob.duplicateCount,
      contentQueuedCount:
        sharedJob.contentQueuedCount ?? localJob.contentQueuedCount,
      contentSkippedCount:
        sharedJob.contentSkippedCount ?? localJob.contentSkippedCount,
    };
  }

  return {
    ...localJob,
    ...sharedJob,
    celeryStatus: sharedJob.celeryStatus ?? localJob.celeryStatus,
    savedCount: sharedJob.savedCount ?? localJob.savedCount,
    updatedCount: sharedJob.updatedCount ?? localJob.updatedCount,
    duplicateCount: sharedJob.duplicateCount ?? localJob.duplicateCount,
    contentQueuedCount:
      sharedJob.contentQueuedCount ?? localJob.contentQueuedCount,
    contentSkippedCount:
      sharedJob.contentSkippedCount ?? localJob.contentSkippedCount,
  };
}

export function mergeJobs(
  localJobs: ParseJob[],
  sharedJobs: SharedParseJob[] | ParseJob[],
): ParseJob[] {
  const byId = new Map<string, ParseJob>();
  for (const job of normalizeJobs(localJobs)) {
    byId.set(job.jobId, job);
  }
  for (const sharedJob of normalizeJobs(sharedJobs)) {
    byId.set(
      sharedJob.jobId,
      preferSharedJob(byId.get(sharedJob.jobId), sharedJob),
    );
  }
  return Array.from(byId.values())
    .sort((a, b) => b.startedAt - a.startedAt)
    .slice(0, 50);
}

export function isExpiredPendingTask(job: ParseJob, now: number): boolean {
  return (
    job.status === "in_progress" &&
    now - job.lastCountChangeAt > STALE_PENDING_TASK_MS &&
    job.lastObservedCount <= job.initialCount
  );
}

export function getCeleryStatusMeta(
  status: CeleryTaskStatus | null | undefined,
): Record<string, unknown> {
  const progress =
    status?.progress && typeof status.progress === "object"
      ? status.progress
      : {};
  const result =
    status?.result && typeof status.result === "object" ? status.result : {};
  return { ...progress, ...result };
}

export function getSavedCountFromStatus(
  status: CeleryTaskStatus | null | undefined,
): number | undefined {
  const meta = getCeleryStatusMeta(status);
  return toNullableFiniteNumber(
    status?.saved_count ??
      status?.total_saved ??
      meta.saved_count ??
      meta.total_saved,
  );
}

export function getParseJobSavedCount(job: ParseJob): number {
  const fromCelery = getSavedCountFromStatus(job.celeryStatus);
  if (fromCelery !== undefined) return Math.max(0, fromCelery);
  if (job.savedCount !== undefined) return Math.max(0, job.savedCount);
  return Math.max(0, job.lastObservedCount - job.initialCount);
}

export function getParseJobProgressPercent(job: ParseJob): number {
  if (job.status === "completed") return 100;
  if (
    job.status === "failed" ||
    job.status === "expired" ||
    job.status === "cancelled"
  )
    return 0;

  const celeryStatus = job.celeryStatus;
  if (celeryStatus) {
    const meta = getCeleryStatusMeta(celeryStatus);
    const explicitPercent = toNullableFiniteNumber(
      meta.percent ?? meta.progress_percent,
    );
    if (explicitPercent !== undefined) return clampPercent(explicitPercent);

    const current = toFiniteNumber(celeryStatus.current ?? meta.current, 0);
    const total = toFiniteNumber(celeryStatus.total ?? meta.total, 0);
    if (total > 0 && current > 0) return clampPercent((current / total) * 100);

    const currentQuery = toFiniteNumber(meta.current_query, 0);
    const totalQueries = toFiniteNumber(meta.total_queries, 0);
    if (totalQueries > 0 && currentQuery > 0)
      return clampPercent((currentQuery / totalQueries) * 100);

    const currentSource = toFiniteNumber(meta.current_source, 0);
    const totalSources = toFiniteNumber(meta.total_sources, 0);
    if (totalSources > 0 && currentSource > 0)
      return clampPercent((currentSource / totalSources) * 100);

    const celeryState = celeryStatus.status;
    const stage = String(meta.stage ?? meta.type ?? "").toLowerCase();
    const elapsed = toFiniteNumber(meta.elapsed_seconds, 0);

    if (celeryState === "PENDING") return 3;
    if (stage === "parser_alpha")
      return clampPercent(8 + Math.min(37, elapsed / 3));
    if (
      stage.includes("read") ||
      stage.includes("result") ||
      stage.includes("parse_results")
    )
      return 46;
    if (stage.includes("save") || stage.includes("saving")) return 55;
    if (
      celeryState === "STARTED" ||
      celeryState === "PROGRESS" ||
      celeryState === "RECEIVED"
    )
      return 8;
  }

  const savedCount = getParseJobSavedCount(job);
  if (savedCount > 0) return clampPercent(Math.min(95, 10 + savedCount * 5));

  const delta = Math.max(0, job.lastObservedCount - job.initialCount);
  const expectedDelta = 50;
  return clampPercent((delta / expectedDelta) * 100);
}

export function getParseJobStatusText(job: ParseJob): string {
  if (job.status === "completed") return "✓ Завершено";
  if (job.status === "failed") return "✕ Ошибка";
  if (job.status === "cancelled") return "Отменено";
  if (job.status === "expired") return "Истёк / не найден";

  const celeryStatus = job.celeryStatus;
  if (!celeryStatus) return "В обработке";

  const meta = getCeleryStatusMeta(celeryStatus);
  const stateText = String(
    meta.status || meta.stage_label || celeryStatus.state || "",
  ).trim();

  if (celeryStatus.status === "SUCCESS") return "✓ Завершено";
  if (celeryStatus.status === "FAILURE")
    return stateText ? `✕ ${stateText}` : "✕ Ошибка";
  if (celeryStatus.status === "REVOKED") return "Отменено";
  if (celeryStatus.status === "PENDING") return "Ожидание…";
  if (celeryStatus.status === "RETRY") return "Повтор…";
  if (celeryStatus.status === "UNKNOWN") return "Статус неизвестен";
  if (celeryStatus.status === "RECEIVED")
    return stateText || "Получено worker-ом…";
  if (celeryStatus.status === "STARTED" || celeryStatus.status === "PROGRESS")
    return stateText || "В процессе…";

  return stateText || "В обработке";
}

export function getParseJobStatusClass(job: ParseJob): string {
  if (job.status === "completed" || job.celeryStatus?.status === "SUCCESS")
    return "active";
  if (job.status === "failed" || job.celeryStatus?.status === "FAILURE")
    return "failed";
  if (job.status === "expired") return "expired";
  if (job.status === "cancelled" || job.celeryStatus?.status === "REVOKED")
    return "cancelled";
  return "processing";
}

export function buildUpdatedJobFromCelery(
  job: ParseJob,
  celeryStatus: CeleryTaskStatus,
  currentTotalCount?: number,
): ParseJob {
  const now = Date.now();
  const isSuccess = celeryStatus.status === "SUCCESS";
  const isFailure = celeryStatus.status === "FAILURE";
  const isRevoked = celeryStatus.status === "REVOKED";
  const savedCount = getSavedCountFromStatus(celeryStatus);

  if (celeryStatus.status === "PENDING" && currentTotalCount !== undefined) {
    const changed = currentTotalCount !== job.lastObservedCount;
    const lastCountChangeAt = changed ? now : job.lastCountChangeAt;
    const stableMs = 60_000;
    const shouldComplete =
      now - lastCountChangeAt > stableMs &&
      currentTotalCount > job.initialCount;
    const expired =
      !shouldComplete &&
      isExpiredPendingTask(
        { ...job, lastObservedCount: currentTotalCount, lastCountChangeAt },
        now,
      );

    return {
      ...job,
      celeryStatus,
      lastObservedCount: currentTotalCount,
      lastCountChangeAt,
      lastPolledAt: now,
      status: shouldComplete
        ? "completed"
        : expired
          ? "expired"
          : "in_progress",
      savedCount: savedCount ?? job.savedCount,
    };
  }

  return {
    ...job,
    celeryStatus,
    lastCountChangeAt:
      isSuccess || isFailure || isRevoked || savedCount !== undefined
        ? now
        : job.lastCountChangeAt,
    lastPolledAt: now,
    status: isRevoked
      ? "cancelled"
      : isFailure
        ? "failed"
        : isSuccess
          ? "completed"
          : "in_progress",
    savedCount: savedCount ?? job.savedCount,
  };
}
