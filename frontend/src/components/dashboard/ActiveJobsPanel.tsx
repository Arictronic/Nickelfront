import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  getCeleryStatusMeta,
  getParseJobProgressPercent,
  getParseJobSavedCount,
  getParseJobStatusClass,
  getParseJobStatusText,
  type ParseJob,
} from "../../utils/parseJobs";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}


function boolish(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (value === null || value === undefined || value === "" || value === 0) return false;
  const text = String(value).trim().toLowerCase();
  return !["0", "false", "no", "none", "null"].includes(text);
}

const SOFT_FAIL_STATUSES = new Set([
  "stage_failed",
  "qwen_stage_failed",
  "pipeline_stage_failed",
  "ready_with_fallback",
  "completed_with_errors",
  "completed_with_warnings",
  "completed_with_fallback",
  "partial_success",
  "partial_success_with_errors",
  "warning",
  "partial",
]);

const PIPELINE_WARNING_KEYS = [
  "pipeline_error",
  "failed_stage",
  "first_failed_stage",
  "failed_task_id",
  "pipeline_error_message",
  "error_message",
  "retry_allowed",
  "fallback_used",
  "markdown_error",
  "keywords_error",
  "embedding_error",
  "qwen_fallback_reason",
  "qwen_used_fallback",
];

function payloadHasPipelineWarning(payload: unknown): boolean {
  const record = asRecord(payload);
  const resultStatus = String(record.status || record.result_status || "").trim();
  const finalStage = String(record.final_stage || "").trim();
  if ([
    "completed_with_errors",
    "completed_with_warnings",
    "completed_with_fallback",
    "partial_success",
    "partial_success_with_errors",
    "warning",
    "partial",
  ].includes(resultStatus)) return true;
  if (SOFT_FAIL_STATUSES.has(resultStatus) || finalStage === "ready_with_fallback") return true;
  if (toNumber(record.errors_count, 0) > 0) return true;
  if (Array.isArray(record.errors) && record.errors.length > 0) return true;
  if (Array.isArray(record.stage_errors) && record.stage_errors.length > 0) return true;
  return PIPELINE_WARNING_KEYS.some((key) => key in record && boolish(record[key]));
}

function payloadErrorText(payload: unknown): string | null {
  const record = asRecord(payload);
  for (const key of ["pipeline_error_message", "error_message", "error", "markdown_error", "keywords_error", "embedding_error", "qwen_fallback_reason"]) {
    const value = record[key];
    if (value) return String(value).slice(0, 240);
  }
  const stageErrors = Array.isArray(record.stage_errors) ? record.stage_errors : [];
  if (stageErrors.length > 0) {
    const first = asRecord(stageErrors[0]);
    return String(first.error_message || first.message || stageErrors[0]).slice(0, 240);
  }
  return null;
}

function parseOutcomeLabel(meta: Record<string, unknown>, docs: ReturnType<typeof getDocumentSummary>): string {
  const outcome = String(meta.outcome || meta.status_reason || "").trim();
  if (outcome === "target_reached") return "Цель выполнена";
  if (outcome === "no_candidates" || outcome === "source_returned_no_candidates") return "Источник не вернул кандидатов";
  if (outcome === "duplicates_only" || outcome === "all_candidates_already_exist") return "Все кандидаты уже есть в базе";
  if (outcome === "target_not_reached" || outcome === "candidate_window_exhausted") return "Цель не достигнута в текущем окне поиска";
  if (docs.saved >= docs.target && docs.target > 0) return "Цель выполнена";
  if (docs.found <= 0 && docs.saved <= 0) return "Источник не вернул кандидатов";
  if (docs.saved <= 0 && docs.duplicates > 0 && docs.duplicates >= docs.examined) return "Все кандидаты уже есть в базе";
  if (docs.saved < docs.target && docs.target > 0) return "Цель не достигнута";
  return "Завершено";
}

function parseOutcomeTone(meta: Record<string, unknown>, docs: ReturnType<typeof getDocumentSummary>): TimelineStatus {
  const outcome = String(meta.outcome || meta.status_reason || "").trim();
  if (outcome === "target_reached" || (docs.target > 0 && docs.saved >= docs.target)) return "completed";
  if (outcome === "no_candidates" || outcome === "source_returned_no_candidates") return "neutral";
  return docs.saved > 0 ? "warning" : "neutral";
}

function relatedPayloads(item: unknown): Record<string, unknown>[] {
  const record = asRecord(item);
  return [record.result, record.info].map(asRecord).filter((payload) => Object.keys(payload).length > 0);
}

function formatDateTime(valueMs: number): string {
  return new Date(valueMs).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(seconds: number): string | null {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds < 60) return `${seconds.toFixed(0)} с`;
  return `${Math.floor(seconds / 60)} мин ${Math.floor(seconds % 60)} с`;
}

function normalizeSourceStatus(status: unknown): string {
  const normalized = String(status || "").trim();
  if ([
    "completed_with_errors",
    "completed_with_warnings",
    "completed_with_fallback",
    "partial_success",
    "partial_success_with_errors",
    "warning",
    "partial",
    "stage_failed",
    "qwen_stage_failed",
    "pipeline_stage_failed",
    "ready_with_fallback",
  ].includes(normalized)) return "partial";
  if (["failed", "FAILURE", "error"].includes(normalized)) return "failed";
  if (["cancelled", "REVOKED", "revoked"].includes(normalized)) return "cancelled";
  if (["completed", "success", "SUCCESS", "ready", "ok"].includes(normalized)) return "completed";
  if (["pending", "queued"].includes(normalized)) return "pending";
  if (["in_progress", "STARTED", "PROGRESS", "RECEIVED"].includes(normalized)) return "in_progress";
  return normalized || "unknown";
}

function statusClass(status: string): string {
  const normalized = normalizeSourceStatus(status);
  if (normalized === "completed") return "active";
  if (normalized === "partial") return "warning";
  if (normalized === "failed") return "failed";
  if (normalized === "cancelled") return "cancelled";
  if (normalized === "pending" || normalized === "unknown") return "neutral";
  return "processing";
}

function statusLabel(status: string): string {
  const normalized = normalizeSourceStatus(status);
  const labels: Record<string, string> = {
    completed: "завершён",
    success: "успешно",
    SUCCESS: "успешно",
    failed: "ошибка",
    FAILURE: "ошибка",
    error: "ошибка",
    cancelled: "отменён",
    REVOKED: "отменён",
    revoked: "отменён",
    pending: "ожидает",
    PENDING: "ожидает",
    queued: "в очереди",
    in_progress: "выполняется",
    processing: "в работе",
    STARTED: "выполняется",
    PROGRESS: "выполняется",
    RETRY: "повтор",
    unknown: "неизвестно",
    UNKNOWN: "неизвестно",
    completed_with_errors: "с ошибками",
    partial_success: "частично",
    partial: "частично",
    warning: "с предупреждением",
    stage_failed: "ошибка этапа",
    qwen_stage_failed: "ошибка Qwen",
    pipeline_stage_failed: "ошибка pipeline",
    ready_with_fallback: "резервный режим",
  };
  return labels[normalized] || labels[String(status || "").trim()] || String(status || "").trim() || "неизвестно";
}


function jobTypeLabel(value: unknown): string {
  const raw = String(value || "parse").trim();
  const labels: Record<string, string> = {
    parse: "Парсинг",
    content_backlog: "Очередь контента",
    vector_rebuild: "Векторный индекс",
    rag_rebuild: "RAG",
    maintenance: "Обслуживание",
  };
  return labels[raw] || raw;
}

function taskNameLabel(value: unknown): string {
  const raw = String(value || "").trim();
  const labels: Record<string, string> = {
    "app.tasks.parse_tasks.parse_papers_task": "Парсинг источника",
    "app.tasks.parse_tasks.parse_all_sources_task": "Парсинг всех источников",
    "app.tasks.dashboard.process_pdf_backlog": "Очередь PDF и контента",
    "app.tasks.dashboard.retry_failed_content": "Повторная обработка ошибок контента",
    "app.tasks.dashboard.rebuild_embeddings": "Сбор эмбеддингов",
    "app.tasks.dashboard.reindex_vector_store": "Синхронизация векторного индекса",
    "app.tasks.dashboard.rebuild_vector_store_full": "Полная пересборка векторного индекса",
    "app.tasks.dashboard.rebuild_rag_index": "Пересборка RAG-индекса",
  };
  return labels[raw] || raw || "";
}

function looksLikeTaskId(value: unknown): value is string {
  const raw = String(value || "").trim();
  if (!raw) return false;
  if (/^test[-_]/i.test(raw)) return false;
  if (/^(mock|demo|sample)[-_]/i.test(raw)) return false;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(raw)) return true;
  return /^[a-zA-Z0-9][a-zA-Z0-9:_-]{15,}$/.test(raw) && /[-_:]/.test(raw);
}

type TaskIdKind = "root" | "content" | "qwen" | "child" | "dashboard" | "celery";

type TaskIdRef = {
  id: string;
  kind: TaskIdKind;
  label: string;
  path: string;
};

function taskKindLabel(kind: TaskIdKind): string {
  const labels: Record<TaskIdKind, string> = {
    root: "Root parse task",
    content: "Content worker",
    qwen: "Qwen worker",
    child: "Дочерние задачи",
    dashboard: "Dashboard/обычные задачи",
    celery: "Прочие Celery task_id",
  };
  return labels[kind];
}

function taskKindClass(kind: TaskIdKind): string {
  const classes: Record<TaskIdKind, string> = {
    root: "processing",
    content: "success",
    qwen: "warning",
    child: "neutral",
    dashboard: "active",
    celery: "neutral",
  };
  return classes[kind];
}

function classifyTaskId(path: string, value: string): TaskIdKind {
  const haystack = `${path} ${value}`.toLowerCase();
  if (/jobid|root[_-]?task|parse[_-]?task|parse_tasks|parse\./i.test(haystack)) return "root";
  if (/qwen|markdown|ru[_-]?analysis|keywords|llm|rag|queue[_-]?qwen/i.test(haystack)) return "qwen";
  if (/content[_-]?task|content_tasks|download[_-]?pdf|extract[_-]?pdf|build[_-]?embedding|embedding|finalize[_-]?paper|pdf[_-]?text|content[_-]?pipeline/i.test(haystack)) return "content";
  if (/dashboard|rebuild|reindex|backlog|retry[_-]?failed/i.test(haystack)) return "dashboard";
  if (/child|children|chain|related|group|chord|workflow|subtask/i.test(haystack)) return "child";
  return "celery";
}

function mergeTaskKind(existing: TaskIdKind, next: TaskIdKind): TaskIdKind {
  const priority: Record<TaskIdKind, number> = {
    root: 6,
    qwen: 5,
    content: 4,
    dashboard: 3,
    child: 2,
    celery: 1,
  };
  return priority[next] > priority[existing] ? next : existing;
}

function collectTaskRefs(value: unknown, result = new Map<string, TaskIdRef>(), path: string[] = [], depth = 0): Map<string, TaskIdRef> {
  if (depth > 12 || value == null) return result;

  if (typeof value === "string") {
    if (looksLikeTaskId(value)) {
      const id = value.trim();
      const pathText = path.join(".") || "root";
      const kind = classifyTaskId(pathText, id);
      const previous = result.get(id);
      if (previous) {
        const mergedKind = mergeTaskKind(previous.kind, kind);
        result.set(id, {
          id,
          kind: mergedKind,
          label: taskKindLabel(mergedKind),
          path: previous.path.length <= pathText.length ? previous.path : pathText,
        });
      } else {
        result.set(id, { id, kind, label: taskKindLabel(kind), path: pathText });
      }
    }
    return result;
  }

  if (Array.isArray(value)) {
    value.forEach((item, index) => collectTaskRefs(item, result, [...path, String(index)], depth + 1));
    return result;
  }

  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const taskName = String(record.name || record.task_name || record.type || "").trim();
    const contextualPath = taskName ? [...path, taskName] : path;

    for (const [key, item] of Object.entries(record)) {
      const nextPath = [...contextualPath, key];
      if (
        /task|celery|child|children|chain|chord|group|workflow|qwen|content|pdf|embedding|markdown|keyword|result|meta|progress|status|id/i.test(key) ||
        typeof item === "object"
      ) {
        collectTaskRefs(item, result, nextPath, depth + 1);
      }
    }
  }
  return result;
}

function taskRefSortWeight(kind: TaskIdKind): number {
  const weights: Record<TaskIdKind, number> = {
    root: 0,
    content: 1,
    qwen: 2,
    child: 3,
    dashboard: 4,
    celery: 5,
  };
  return weights[kind];
}

function groupTaskRefs(refs: TaskIdRef[]): { kind: TaskIdKind; label: string; items: TaskIdRef[] }[] {
  const groups = new Map<TaskIdKind, TaskIdRef[]>();
  for (const ref of refs) {
    const list = groups.get(ref.kind) || [];
    list.push(ref);
    groups.set(ref.kind, list);
  }
  return Array.from(groups.entries())
    .sort(([left], [right]) => taskRefSortWeight(left) - taskRefSortWeight(right))
    .map(([kind, items]) => ({
      kind,
      label: taskKindLabel(kind),
      items: items.sort((a, b) => a.id.localeCompare(b.id)),
    }));
}

function shortTaskId(taskId: string): string {
  if (taskId.length <= 18) return taskId;
  return `${taskId.slice(0, 8)}…${taskId.slice(-6)}`;
}

function nonEmptyText(value: unknown): string | null {
  const text = String(value || "").trim();
  if (!text || text === "—") return null;
  return text;
}

const JOBS_PER_PAGE = 5;
const MAX_TASK_REFS_PER_JOB = 300;

type TimelineStatus = "completed" | "processing" | "pending" | "failed" | "warning" | "neutral";

type TimelineEvent = {
  key: string;
  label: string;
  description: string;
  status: TimelineStatus;
  value?: string;
};

type StageTimelineTask = {
  stage: string;
  label: string;
  taskId: string | null;
  status: TimelineStatus;
  rawStatus: string;
};

const PIPELINE_STAGE_ORDER = [
  "download_pdf",
  "extract_pdf_text",
  "qwen_ai_ocr_document",
  "qwen_markdown",
  "qwen_ru_analysis",
  "qwen_keywords",
  "build_embedding",
  "finalize",
];

const PIPELINE_STAGE_LABELS: Record<string, string> = {
  download_pdf: "Скачивание PDF",
  extract_pdf_text: "Извлечение текста",
  qwen_ai_ocr_document: "AI OCR через Qwen",
  qwen_markdown: "Qwen Markdown",
  qwen_ru_analysis: "Русский анализ",
  qwen_keywords: "Ключевые слова",
  build_embedding: "Embedding / Chroma",
  finalize: "Финализация документа",
};

const PIPELINE_STAGE_DESCRIPTIONS: Record<string, string> = {
  download_pdf: "Скачивание PDF или фиксация, что PDF недоступен",
  extract_pdf_text: "Извлечение текста/страниц из PDF или fallback full-text",
  qwen_ai_ocr_document: "Документный OCR по изображениям страниц через Qwen",
  qwen_markdown: "Нормализация текста статьи в Markdown",
  qwen_ru_analysis: "Русская аннотация, анализ и переводный слой",
  qwen_keywords: "Ключевые слова, проверенные по тексту документа",
  build_embedding: "Эмбеддинг и обновление векторного индекса",
  finalize: "Итоговый статус статьи после downstream pipeline",
};

function toNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function timelineStatusClass(status: TimelineStatus): string {
  if (status === "completed") return "success";
  if (status === "failed") return "failed";
  if (status === "warning") return "warning";
  if (status === "pending") return "pending";
  if (status === "neutral") return "neutral";
  return "processing";
}

function isJobTerminal(job: ParseJob): boolean {
  return ["completed", "partial", "failed", "cancelled", "expired"].includes(job.status);
}

function timelineStatusFromCelery(raw: unknown, payload?: unknown): TimelineStatus {
  if (payloadHasPipelineWarning(payload)) return "warning";
  const status = String(raw || "").trim().toUpperCase();
  const rawText = String(raw || "").trim();
  if (SOFT_FAIL_STATUSES.has(rawText)) return "warning";
  if (status === "SUCCESS") return "completed";
  if (status === "FAILURE") return "failed";
  if (status === "REVOKED") return "neutral";
  if (["STARTED", "PROGRESS", "RECEIVED", "RETRY"].includes(status)) return "processing";
  if (status === "PENDING" || status === "UNKNOWN") return "pending";
  return "pending";
}

function collectRelatedStatusRecords(status: ParseJob["celeryStatus"]): Record<string, Record<string, unknown>> {
  const byId: Record<string, Record<string, unknown>> = {};
  const related = Array.isArray(status?.related_child_statuses) ? status.related_child_statuses : [];
  for (const item of related) {
    const record = asRecord(item);
    const taskId = String(record.task_id || "").trim();
    if (taskId) byId[taskId] = record;
  }
  return byId;
}

function collectStageDescriptors(value: unknown, result = new Map<string, StageTimelineTask>(), depth = 0): Map<string, StageTimelineTask> {
  if (depth > 8 || value == null) return result;

  if (Array.isArray(value)) {
    for (const item of value) {
      const record = asRecord(item);
      const stage = String(record.stage || "").trim();
      const taskId = String(record.task_id || record.taskId || "").trim();
      if (stage && (PIPELINE_STAGE_LABELS[stage] || taskId)) {
        result.set(stage, {
          stage,
          label: String(record.label || PIPELINE_STAGE_LABELS[stage] || stage),
          taskId: taskId || null,
          status: "pending",
          rawStatus: "UNKNOWN",
        });
      }
      collectStageDescriptors(record.result, result, depth + 1);
      collectStageDescriptors(record.info, result, depth + 1);
      collectStageDescriptors(record.stage_tasks, result, depth + 1);
    }
    return result;
  }

  const record = asRecord(value);
  const stageTasks = Array.isArray(record.stage_tasks) ? record.stage_tasks : [];
  if (stageTasks.length) collectStageDescriptors(stageTasks, result, depth + 1);

  const stageTaskIds = asRecord(record.stage_task_ids);
  for (const [stage, taskIdValue] of Object.entries(stageTaskIds)) {
    const taskId = String(taskIdValue || "").trim();
    if (!stage || !taskId) continue;
    if (!result.has(stage)) {
      result.set(stage, {
        stage,
        label: PIPELINE_STAGE_LABELS[stage] || stage,
        taskId,
        status: "pending",
        rawStatus: "UNKNOWN",
      });
    } else {
      const existing = result.get(stage)!;
      result.set(stage, { ...existing, taskId: existing.taskId || taskId });
    }
  }

  collectStageDescriptors(record.result, result, depth + 1);
  collectStageDescriptors(record.info, result, depth + 1);
  collectStageDescriptors(record.related_child_statuses, result, depth + 1);
  return result;
}

function buildPipelineStageEvents(job: ParseJob, meta: Record<string, unknown>): TimelineEvent[] {
  const descriptors = collectStageDescriptors({
    celeryStatus: job.celeryStatus,
    meta,
    result: job.celeryStatus?.result,
    related_child_statuses: job.celeryStatus?.related_child_statuses,
    stage_task_ids: job.celeryStatus?.stage_task_ids,
    stage_tasks: job.celeryStatus?.stage_tasks,
  });
  if (descriptors.size === 0) return [];

  const relatedById = collectRelatedStatusRecords(job.celeryStatus);
  const orderedStages = Array.from(descriptors.values()).sort((a, b) => {
    const left = PIPELINE_STAGE_ORDER.indexOf(a.stage);
    const right = PIPELINE_STAGE_ORDER.indexOf(b.stage);
    return (left < 0 ? 999 : left) - (right < 0 ? 999 : right);
  });

  return orderedStages.map((stage) => {
    const related = stage.taskId ? relatedById[stage.taskId] : undefined;
    const payloads = relatedPayloads(related);
    const warningPayload = payloads.find(payloadHasPipelineWarning);
    const rawStatus = String(related?.status || related?.state || warningPayload?.status || stage.rawStatus || "UNKNOWN");
    const taskState = timelineStatusFromCelery(rawStatus, warningPayload);
    const value = stage.taskId ? shortTaskId(stage.taskId) : undefined;
    const errorText = payloadErrorText(warningPayload);
    const baseDescription = `${PIPELINE_STAGE_DESCRIPTIONS[stage.stage] || "Этап downstream pipeline"}${value ? ` · task ${value}` : ""}`;
    return {
      key: `stage:${stage.stage}:${stage.taskId || stage.label}`,
      label: stage.label,
      description: errorText ? `${baseDescription}. Ошибка/fallback: ${errorText}` : baseDescription,
      status: taskState,
      value: warningPayload ? statusLabel(String(warningPayload.status || warningPayload.final_stage || "warning")) : rawStatus && rawStatus !== "UNKNOWN" ? statusLabel(rawStatus) : value,
    };
  });
}

function getDocumentSummary(job: ParseJob, meta: Record<string, unknown>) {
  const found = toNumber(meta.found_count ?? meta.parsed_count, 0);
  const parsed = toNumber(meta.parsed_count ?? meta.found_count, 0);
  const saved = toNumber(job.savedCount ?? meta.saved_count ?? meta.total_saved, 0);
  const updated = toNumber(job.updatedCount ?? meta.updated_count ?? meta.total_updated, 0);
  const duplicates = toNumber(job.duplicateCount ?? meta.duplicate_count ?? meta.total_duplicates, 0);
  const queued = toNumber(job.contentQueuedCount ?? meta.content_queued_count ?? meta.total_content_queued, 0);
  const skipped = toNumber(job.contentSkippedCount ?? meta.content_skipped_count ?? meta.total_content_skipped, 0);
  const errors = toNumber(meta.errors_count ?? (Array.isArray(meta.errors) ? meta.errors.length : 0), 0);
  const target = toNumber(meta.target_new_count ?? meta.total ?? job.celeryStatus?.total, 0);
  const candidateLimit = toNumber(meta.candidate_limit, 0);
  const examined = toNumber(meta.examined_count ?? meta.current ?? job.celeryStatus?.current, 0);

  const produced = saved + updated + duplicates + skipped;
  const downstreamTotal = queued + skipped;
  const naturalTotal = Math.max(target, examined, produced, downstreamTotal, 0);
  const terminal = isJobTerminal(job);
  const processed = target > 0 ? saved : terminal ? Math.max(naturalTotal, produced, downstreamTotal) : Math.min(Math.max(produced, examined), naturalTotal || Math.max(produced, examined));
  const total = target > 0 ? target : Math.max(naturalTotal, processed, produced, downstreamTotal);
  const percent = target > 0 ? Math.max(0, Math.min(100, Math.round((saved / target) * 100))) : total > 0 ? Math.max(0, Math.min(100, Math.round((processed / total) * 100))) : getParseJobProgressPercent(job);

  return {
    found,
    parsed,
    saved,
    updated,
    duplicates,
    queued,
    skipped,
    errors,
    target,
    candidateLimit,
    examined,
    processed,
    total,
    percent,
  };
}

function buildTimeline(job: ParseJob, meta: Record<string, unknown>, taskIds: string[], stageEvents: TimelineEvent[]): TimelineEvent[] {
  const docs = getDocumentSummary(job, meta);
  const stage = String(meta.stage ?? meta.stage_label ?? "").toLowerCase();
  const terminal = isJobTerminal(job);
  const failed = job.status === "failed" || job.celeryStatus?.status === "FAILURE";
  const partial = job.status === "partial";
  const running = !terminal;

  const hasSearchActivity = docs.examined > 0 || docs.saved > 0 || docs.updated > 0 || docs.duplicates > 0 || stage.includes("parser") || stage.includes("search");
  const hasSavedActivity = docs.saved > 0 || docs.updated > 0 || docs.duplicates > 0;
  const hasContentActivity = docs.queued > 0 || docs.skipped > 0 || stageEvents.length > 0;
  const hasActiveStage = stageEvents.some((event) => event.status === "processing" || event.status === "pending");
  const hasFailedStage = stageEvents.some((event) => event.status === "failed");
  const hasWarningStage = stageEvents.some((event) => event.status === "warning");
  const hasErrors = docs.errors > 0 || failed || hasFailedStage;
  const hasNewDocuments = docs.saved > 0;
  const parseOutcome = parseOutcomeLabel(meta, docs);
  const parseOutcomeStatus = parseOutcomeTone(meta, docs);

  const searchStatus: TimelineStatus = failed && !hasSearchActivity ? "failed" : parseOutcomeStatus === "neutral" && terminal ? "neutral" : hasSearchActivity || terminal ? "completed" : "processing";
  const saveStatus: TimelineStatus = failed && !hasSavedActivity ? "failed" : hasSavedActivity ? "completed" : running ? "pending" : "neutral";
  const contentQueueStatus: TimelineStatus = hasContentActivity ? (docs.queued > 0 ? "completed" : "neutral") : running && hasNewDocuments ? "pending" : "neutral";
  const fallbackContentStatus: TimelineStatus = failed && hasContentActivity ? "failed" : hasContentActivity && terminal ? (partial || hasErrors ? "warning" : "completed") : hasContentActivity ? "processing" : running && hasNewDocuments ? "pending" : "neutral";
  const fallbackKeywordsStatus: TimelineStatus = fallbackContentStatus === "completed" ? "completed" : fallbackContentStatus === "failed" ? "failed" : fallbackContentStatus === "warning" ? "warning" : hasContentActivity ? "processing" : running && hasNewDocuments ? "pending" : "neutral";
  const finalStatus: TimelineStatus = failed || hasFailedStage ? "failed" : partial || hasErrors || hasWarningStage || (terminal && docs.target > 0 && docs.saved < docs.target && docs.saved > 0) ? "warning" : job.status === "completed" && !hasActiveStage ? parseOutcomeStatus : job.status === "cancelled" || job.status === "expired" ? "neutral" : "pending";

  const downstreamEvents: TimelineEvent[] = stageEvents.length > 0
    ? stageEvents
    : [
        {
          key: "content",
          label: "PDF, текст и Qwen-обработка",
          description: hasContentActivity ? "Скачивание/извлечение текста, markdown/RU-анализ и подготовка документа" : "Ожидает content worker",
          status: fallbackContentStatus,
        },
        {
          key: "keywords",
          label: "Ключевые слова и индексация",
          description: hasContentActivity ? "Формирование ключевых слов, эмбеддинги и обновление индекса" : "Будет выполнено после content pipeline",
          status: fallbackKeywordsStatus,
        },
      ];

  return [
    {
      key: "created",
      label: "Задача создана",
      description: `Источник: ${job.source || "all"}; запрос: ${job.query || "без запроса"}`,
      status: "completed",
      value: formatDateTime(job.startedAt),
    },
    {
      key: "search",
      label: "Поиск статей/патентов",
      description: docs.candidateLimit > 0 ? `Проверено кандидатов: ${docs.examined}/${docs.candidateLimit}` : docs.examined > 0 ? `Проверено кандидатов: ${docs.examined}` : "Ожидание результатов парсера",
      status: searchStatus,
    },
    {
      key: "save",
      label: "Сохранение и дедупликация",
      description: `Сохранено ${docs.saved}, обновлено ${docs.updated}, дубликатов ${docs.duplicates}`,
      status: saveStatus,
    },
    {
      key: "queue",
      label: "Постановка PDF/content pipeline",
      description: docs.queued > 0 || docs.skipped > 0 ? `В очередь ${docs.queued}, пропущено ${docs.skipped}` : "Документы ещё не поставлены в downstream-обработку",
      status: contentQueueStatus,
    },
    ...downstreamEvents,
    {
      key: "tasks",
      label: "Связанные Celery-задачи",
      description: taskIds.length > 0 ? `${taskIds.length} task_id найдено в root/result/meta` : "Связанные task_id пока не найдены",
      status: taskIds.length > 0 ? "completed" : "pending",
    },
    {
      key: "final",
      label: "Финализация партии",
      description: failed ? "Задача завершилась ошибкой" : partial || hasErrors ? `Есть ошибки: ${docs.errors || "см. подробности"}` : job.status === "completed" && !hasActiveStage ? "Партия и downstream-этапы обработаны" : "Ожидается завершение downstream-этапов",
      status: finalStatus,
    },
  ];
}


interface Props {
  jobs: ParseJob[];
  expandedJobId: string | null;
  onToggle: (jobId: string) => void;
  isAdmin: boolean;
  onCancel: (jobId: string) => void;
  onDelete: (jobId: string) => void;
}

export default function ActiveJobsPanel({ jobs, expandedJobId, isAdmin, onToggle, onCancel, onDelete }: Props) {
  const panelRef = useRef<HTMLElement | null>(null);
  const shouldScrollToPanelTopRef = useRef(false);
  const firstJobId = jobs[0]?.jobId || "";
  const [currentPage, setCurrentPage] = useState(1);
  const totalJobs = jobs.length;
  const totalPages = Math.max(1, Math.ceil(totalJobs / JOBS_PER_PAGE));
  const safePage = Math.max(1, Math.min(currentPage, totalPages));
  const pageStartIndex = (safePage - 1) * JOBS_PER_PAGE;
  const pageEndIndex = Math.min(pageStartIndex + JOBS_PER_PAGE, totalJobs);
  const activeCount = jobs.filter((job) => job.status === "in_progress").length;
  const visibleJobs = useMemo(
    () => jobs.slice(pageStartIndex, pageStartIndex + JOBS_PER_PAGE),
    [jobs, pageStartIndex],
  );
  const pageNumbers = useMemo(
    () => Array.from({ length: totalPages }, (_, index) => index + 1),
    [totalPages],
  );

  const goToPage = (nextPage: number) => {
    const boundedPage = Math.max(1, Math.min(totalPages, nextPage));
    if (boundedPage === safePage) return;

    shouldScrollToPanelTopRef.current = true;
    setCurrentPage(boundedPage);

    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  };

  useLayoutEffect(() => {
    if (!shouldScrollToPanelTopRef.current) return;
    shouldScrollToPanelTopRef.current = false;

    const panel = panelRef.current;
    if (!panel) return;

    const stickyHeaderOffset = 16;
    const nextTop = Math.max(0, panel.getBoundingClientRect().top + window.scrollY - stickyHeaderOffset);
    window.scrollTo({ left: window.scrollX, top: nextTop, behavior: "auto" });
  }, [safePage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [firstJobId]);

  useEffect(() => {
    setCurrentPage((page) => Math.max(1, Math.min(page, totalPages)));
  }, [totalPages]);

  return (
    <section className="panel dashboard-jobs-panel" ref={panelRef}>
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Задачи Celery</span>
          <h3>Фоновые задачи</h3>
        </div>
        <div className="dashboard-jobs-head-status">
          <span className="status processing">{activeCount} активных</span>
          {totalJobs > 0 && <small>{totalJobs} всего · по {JOBS_PER_PAGE} на странице</small>}
        </div>
      </div>

      {visibleJobs.length === 0 ? (
        <div className="dashboard-empty-box">
          <strong>Задачи появятся после запуска фоновых операций</strong>
          <p>Главная будет показывать прогресс парсинга, content pipeline, vector/RAG rebuild и другие фоновые операции.</p>
        </div>
      ) : (
        <>
          <div className="dashboard-job-list">
          {visibleJobs.map((job) => {
            const statusText = getParseJobStatusText(job);
            const meta = getCeleryStatusMeta(job.celeryStatus);
            const documentSummary = getDocumentSummary(job, meta);
            const parseOutcome = parseOutcomeLabel(meta, documentSummary);
            const progress = documentSummary.percent;
            const savedCount = getParseJobSavedCount(job);
            const updatedCount = Number(job.updatedCount ?? meta.updated_count ?? meta.total_updated ?? 0) || 0;
            const duplicates = Number(job.duplicateCount ?? meta.duplicate_count ?? meta.total_duplicates ?? 0) || 0;
            const queued = Number(job.contentQueuedCount ?? meta.content_queued_count ?? meta.total_content_queued ?? 0) || 0;
            const skipped = Number(job.contentSkippedCount ?? meta.content_skipped_count ?? meta.total_content_skipped ?? 0) || 0;
            const current = Number(job.celeryStatus?.current ?? meta.current ?? 0) || 0;
            const total = Number(job.celeryStatus?.total ?? meta.total ?? 0) || 0;
            const targetNew = Number(meta.target_new_count ?? total ?? 0) || 0;
            const examined = Number(meta.examined_count ?? 0) || 0;
            const candidateLimit = Number(meta.candidate_limit ?? targetNew ?? 0) || 0;
            const elapsed = Number(meta.elapsed_seconds ?? 0) || 0;
            const durationText = formatDuration(elapsed);
            const stage = nonEmptyText(meta.stage_label || meta.stage);
            const errorText = nonEmptyText(meta.error || job.celeryStatus?.error);
            const rawTaskName = String(job.celeryStatus?.name || meta.name || meta.type || "");
            const typeLabel = jobTypeLabel(job.jobType || meta.job_type || meta.jobType);
            const taskNameText = nonEmptyText(taskNameLabel(rawTaskName));
            const taskLabel = taskNameText && taskNameText !== typeLabel ? `${typeLabel} · ${taskNameText}` : typeLabel;
            const isParseTask = rawTaskName.includes("parse_tasks") || (job.source !== "dashboard" && !rawTaskName.includes("dashboard"));
            const displayStatusText = isParseTask && isJobTerminal(job) && documentSummary.target > 0 && documentSummary.saved < documentSummary.target
              ? parseOutcome
              : statusText;
            const displayStatusClass = isParseTask && isJobTerminal(job) && documentSummary.target > 0 && documentSummary.saved < documentSummary.target
              ? timelineStatusClass(parseOutcomeTone(meta, documentSummary))
              : getParseJobStatusClass(job);
            const isExpanded = expandedJobId === job.jobId;
            const sourceDetailsRaw = asRecord(meta.sources_status ?? meta.sources ?? job.celeryStatus?.result?.sources_status);
            const taskRefs = Array.from(collectTaskRefs({ job, jobId: job.jobId, celeryStatus: job.celeryStatus, meta }).values())
              .sort((a, b) => taskRefSortWeight(a.kind) - taskRefSortWeight(b.kind) || a.id.localeCompare(b.id))
              .slice(0, MAX_TASK_REFS_PER_JOB);
            const taskIds = taskRefs.map((ref) => ref.id);
            const taskRefGroups = groupTaskRefs(taskRefs);
            const primaryTaskId = taskIds[0] || null;
            const stageEvents = buildPipelineStageEvents(job, meta);
            const timeline = buildTimeline(job, meta, taskIds, stageEvents);
            const perSourceRows = Object.entries(sourceDetailsRaw).map(([name, value]) => {
              const item = asRecord(value);
              const targetNew = Number(item.target_new_count || 0) || 0;
              const examined = Number(item.examined_count || 0) || 0;
              const refillExhausted = Boolean(item.refill_exhausted);
              const error = nonEmptyText(item.error);
              return {
                name,
                status: String(item.status_key || item.status || "unknown"),
                statusLabel: nonEmptyText(item.status_label),
                saved: Number(item.saved_count || 0) || 0,
                updated: Number(item.updated_count || 0) || 0,
                duplicates: Number(item.duplicate_count || 0) || 0,
                queued: Number(item.content_queued_count || 0) || 0,
                skipped: Number(item.content_skipped_count || 0) || 0,
                targetNew,
                examined,
                refillExhausted,
                progressText: targetNew > 0 || examined > 0 ? `пров. ${examined}/${targetNew || "?"} новых` : null,
                note: error || (refillExhausted ? "новые записи закончились" : null),
              };
            });
            const indexedCount = Number(meta.indexed_count ?? meta.indexed ?? meta.embedded_count ?? 0) || 0;
            const errorsCount = Number(meta.errors_count ?? (Array.isArray(meta.errors) ? meta.errors.length : 0)) || 0;
            const childTasksCount = Number(meta.child_tasks_count ?? (Array.isArray(meta.child_task_ids) ? meta.child_task_ids.length : 0)) || 0;
            const metrics = [
              { label: "Сохранено", value: savedCount, show: !isParseTask && savedCount > 0 },
              { label: "Обновлено", value: updatedCount, show: updatedCount > 0 },
              { label: "Дубликаты", value: duplicates, show: duplicates > 0 },
              { label: "Очередь PDF", value: queued, show: !isParseTask && queued > 0 },
              { label: "Пропущено", value: skipped, show: skipped > 0 },
              { label: "Индексировано", value: indexedCount, show: indexedCount > 0 },
              { label: "Дочерних задач", value: childTasksCount, show: !isParseTask && childTasksCount > 0 },
              { label: "Ошибок", value: errorsCount, show: errorsCount > 0 },
            ].filter((item) => item.show);

            return (
              <article key={job.jobId} className="dashboard-job-card">
                <div className="dashboard-job-card-head">
                  <div>
                    <strong>{job.source} · {job.query || "без запроса"}</strong>
                    {taskLabel && <small>{taskLabel}</small>}
                    {primaryTaskId && (
                      <small className="dashboard-job-primary-id">ID задачи: <code title={primaryTaskId}>{shortTaskId(primaryTaskId)}</code></small>
                    )}
                  </div>
                  <span className={`status ${displayStatusClass}`}>{displayStatusText}</span>
                </div>
                <div className="dashboard-job-progress-row">
                  <div className={`dashboard-progress-track dashboard-progress-track--${displayStatusClass}`}><div style={{ width: `${progress}%` }} /></div>
                  <span>{progress}%</span>
                </div>
                <div className="dashboard-job-doc-progress">
                  <span>{isParseTask ? "Новые статьи: добавлено из цели" : "Общий прогресс обработки документов"}</span>
                  <strong>{documentSummary.total > 0 ? `${documentSummary.processed}/${documentSummary.total}` : "—"}</strong>
                </div>
                <div className="dashboard-job-metrics">
                  {metrics.map((item) => (
                    <span key={item.label}>{item.label} <strong>{item.value}</strong></span>
                  ))}
                </div>
                <div className="dashboard-job-footer">
                  <span>Старт: {formatDateTime(job.startedAt)}</span>
                  {!isParseTask && total > 0 && <span>Счётчик: {current}/{total}</span>}
                  {durationText && <span>Длительность: {durationText}</span>}
                  <div className="actions-inline">
                    <button className="btn" type="button" onClick={() => onToggle(job.jobId)}>{isExpanded ? "Скрыть" : "Подробнее"}</button>
                    {isAdmin ? (
                      job.status === "in_progress" && job.celeryStatus?.status !== "REVOKED" ? (
                        <button className="btn" type="button" onClick={() => onCancel(job.jobId)}>Остановить</button>
                      ) : (
                        <button className="btn btn-danger" type="button" onClick={() => onDelete(job.jobId)}>Удалить</button>
                      )
                    ) : (
                      <span className="status neutral" title="Остановка и удаление задач доступны только администратору">Только просмотр</span>
                    )}
                  </div>
                </div>
                {isExpanded && (
                  <div className="dashboard-job-details-card">
                    <div className="dashboard-job-details-grid">
                      {stage && <div><strong>Этап:</strong> {stage}</div>}
                      <div><strong>Celery:</strong> {statusLabel(String(job.celeryStatus?.status || job.celeryStatus?.state || "UNKNOWN"))}</div>
                      <div><strong>Обновлено:</strong> {formatDateTime(job.lastCountChangeAt)}</div>
                      {targetNew > 0 && <div><strong>Цель:</strong> добавить {targetNew} новых</div>}
                      {isParseTask && <div><strong>Источник вернул:</strong> {documentSummary.found} кандидатов</div>}
                      {isParseTask && <div><strong>Проверено:</strong> {examined} из {candidateLimit || documentSummary.found || targetNew} кандидатов</div>}
                      {isParseTask && <div><strong>Результат:</strong> новых {savedCount}, обновлено {updatedCount}, дубликатов {duplicates}</div>}
                      {isParseTask && <div><strong>Итог:</strong> {parseOutcome}</div>}
                    </div>
                    <div className="dashboard-job-timeline">
                      {timeline.map((event) => (
                        <div className={`dashboard-timeline-event dashboard-timeline-event--${timelineStatusClass(event.status)}`} key={`${job.jobId}:${event.key}`}>
                          <span className="dashboard-timeline-dot" aria-hidden="true" />
                          <div className="dashboard-timeline-body">
                            <div className="dashboard-timeline-head">
                              <strong>{event.label}</strong>
                              <span className={`status ${timelineStatusClass(event.status)}`}>{statusLabel(event.status)}</span>
                            </div>
                            <p>{event.description}</p>
                            {event.value && <small>{event.value}</small>}
                          </div>
                        </div>
                      ))}
                    </div>
                    {taskRefs.length > 0 && (
                      <details className="dashboard-task-id-details">
                        <summary>Связанные task_id ({taskRefs.length})</summary>
                        <div className="dashboard-task-id-groups">
                          {taskRefGroups.map((group) => (
                            <div className="dashboard-task-id-group" key={`${job.jobId}:${group.kind}`}>
                              <div className="dashboard-task-id-group-head">
                                <span className={`status ${taskKindClass(group.kind)}`}>{group.label}</span>
                                <small>{group.items.length}</small>
                              </div>
                              <div className="dashboard-task-id-list">
                                {group.items.map((ref) => (
                                  <code key={ref.id} title={`${ref.id}
${ref.path}`}>{shortTaskId(ref.id)}</code>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                    {perSourceRows.length > 0 && (
                      <div className="dashboard-source-mini-table">
                        {perSourceRows.map((row) => (
                          <div className="dashboard-source-mini-row" key={`${job.jobId}:${row.name}`}>
                            <span className="dashboard-source-mini-name">{row.name}</span>
                            <span className={`status ${statusClass(row.status)}`}>{row.statusLabel || statusLabel(row.status)}</span>
                            {row.saved > 0 && <span>сохр. {row.saved}</span>}
                            {row.updated > 0 && <span>обн. {row.updated}</span>}
                            {row.duplicates > 0 && <span>дубл. {row.duplicates}</span>}
                            {row.queued > 0 && <span>PDF {row.queued}</span>}
                            {row.skipped > 0 && <span>проп. {row.skipped}</span>}
                            {row.progressText && <span>{row.progressText}</span>}
                            {row.note && <span className="dashboard-source-mini-note">{row.note}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                    {errorText && <p className="error"><strong>Ошибка:</strong> {errorText}</p>}
                  </div>
                )}
              </article>
            );
          })}
          </div>
          {totalPages > 1 && (
            <div className="dashboard-jobs-pagination" aria-label="Пагинация парсинг-задач">
              <button
                className="btn"
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => goToPage(safePage - 1)}
                disabled={safePage <= 1}
              >
                Назад
              </button>
              <div className="dashboard-jobs-page-buttons">
                {pageNumbers.map((page) => (
                  <button
                    key={page}
                    className={`btn dashboard-jobs-page-button${page === safePage ? " active" : ""}`}
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => goToPage(page)}
                    aria-current={page === safePage ? "page" : undefined}
                  >
                    {page}
                  </button>
                ))}
              </div>
              <button
                className="btn"
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => goToPage(safePage + 1)}
                disabled={safePage >= totalPages}
              >
                Вперёд
              </button>
              <span className="dashboard-jobs-pagination-summary">
                Показано {pageStartIndex + 1}–{pageEndIndex} из {totalJobs}
              </span>
            </div>
          )}
        </>
      )}
    </section>
  );
}
