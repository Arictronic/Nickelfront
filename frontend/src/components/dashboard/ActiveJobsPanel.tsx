import { Fragment } from "react";
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

function formatDateTime(valueMs: number): string {
  return new Date(valueMs).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)} с`;
  return `${Math.floor(seconds / 60)} мин ${Math.floor(seconds % 60)} с`;
}

function statusLabel(status: string): string {
  const normalized = String(status || "").trim();
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
    STARTED: "выполняется",
    PROGRESS: "выполняется",
    RETRY: "повтор",
    unknown: "неизвестно",
    UNKNOWN: "неизвестно",
  };
  return labels[normalized] || normalized || "неизвестно";
}

function taskNameLabel(value: unknown): string {
  const raw = String(value || "").trim();
  const labels: Record<string, string> = {
    "app.tasks.parse_tasks.parse_papers_task": "Парсинг источника",
    "app.tasks.parse_tasks.parse_all_sources_task": "Парсинг всех источников",
    "app.tasks.dashboard.process_pdf_backlog": "Очередь PDF/контента",
    "app.tasks.dashboard.retry_failed_content": "Повтор обработки контента",
    "app.tasks.dashboard.rebuild_embeddings": "Сбор эмбеддингов",
    "app.tasks.dashboard.reindex_vector_store": "Переиндексация Chroma",
  };
  return labels[raw] || raw || "—";
}

function looksLikeTaskId(value: unknown): value is string {
  const raw = String(value || "").trim();
  if (!raw) return false;
  if (/^test[-_]/i.test(raw)) return false;
  if (/^(mock|demo|sample)[-_]/i.test(raw)) return false;
  return /^[a-zA-Z0-9][a-zA-Z0-9:_-]{7,}$/.test(raw);
}

function collectTaskIds(value: unknown, result = new Set<string>(), depth = 0): Set<string> {
  if (depth > 5 || value == null) return result;
  if (typeof value === "string") {
    if (looksLikeTaskId(value)) result.add(value);
    return result;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectTaskIds(item, result, depth + 1));
    return result;
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const [key, item] of Object.entries(record)) {
      if (/task[_-]?id|content[_-]?task|root[_-]?task|chain[_-]?result/i.test(key)) {
        collectTaskIds(item, result, depth + 1);
      } else if (typeof item === "object") {
        collectTaskIds(item, result, depth + 1);
      }
    }
  }
  return result;
}

function shortTaskId(taskId: string): string {
  if (taskId.length <= 18) return taskId;
  return `${taskId.slice(0, 8)}…${taskId.slice(-6)}`;
}

interface Props {
  jobs: ParseJob[];
  expandedJobId: string | null;
  onToggle: (jobId: string) => void;
  onCancel: (jobId: string) => void;
  onDelete: (jobId: string) => void;
}

export default function ActiveJobsPanel({ jobs, expandedJobId, onToggle, onCancel, onDelete }: Props) {
  const visibleJobs = jobs.slice(0, 8);
  return (
    <section className="panel dashboard-jobs-panel">
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Задачи Celery</span>
          <h3>Парсинг-задачи</h3>
        </div>
        <span className="status processing">{jobs.filter((job) => job.status === "in_progress").length} активных</span>
      </div>

      {visibleJobs.length === 0 ? (
        <div className="dashboard-empty-box">
          <strong>Задачи появятся после запуска парсинга</strong>
          <p>Главная будет показывать прогресс, сохранённые записи, дубликаты и детализацию по источникам.</p>
        </div>
      ) : (
        <div className="dashboard-job-list">
          {visibleJobs.map((job) => {
            const progress = getParseJobProgressPercent(job);
            const statusText = getParseJobStatusText(job);
            const meta = getCeleryStatusMeta(job.celeryStatus);
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
            const refillExhausted = Boolean(meta.refill_exhausted);
            const elapsed = Number(meta.elapsed_seconds ?? 0) || 0;
            const stage = String(meta.stage_label || meta.stage || "").trim();
            const errorText = String(meta.error || job.celeryStatus?.error || "").trim();
            const isExpanded = expandedJobId === job.jobId;
            const sourceDetailsRaw = asRecord(meta.sources_status ?? meta.sources ?? job.celeryStatus?.result?.sources_status);
            const taskIds = Array.from(collectTaskIds({ jobId: job.jobId, celeryStatus: job.celeryStatus, meta })).slice(0, 80);
            const primaryTaskId = taskIds[0] || null;
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
                targetNew: Number(item.target_new_count || 0) || 0,
                examined: Number(item.examined_count || 0) || 0,
                refillExhausted: Boolean(item.refill_exhausted),
                error: String(item.error || "").trim(),
              };
            });

            return (
              <article key={job.jobId} className="dashboard-job-card">
                <div className="dashboard-job-card-head">
                  <div>
                    <strong>{job.source} · {job.query || "без запроса"}</strong>
                    <small>{taskNameLabel(job.celeryStatus?.name || meta.name || meta.type)}</small>
                    {primaryTaskId && (
                      <small className="dashboard-job-primary-id">ID задачи: <code title={primaryTaskId}>{shortTaskId(primaryTaskId)}</code></small>
                    )}
                  </div>
                  <span className={`status ${getParseJobStatusClass(job)}`}>{statusText}</span>
                </div>
                <div className="dashboard-job-progress-row">
                  <div className="dashboard-progress-track"><div style={{ width: `${progress}%` }} /></div>
                  <span>{progress}%</span>
                </div>
                <div className="dashboard-job-metrics">
                  <span>Сохранено <strong>{savedCount}</strong></span>
                  <span>Обновлено <strong>{updatedCount}</strong></span>
                  <span>Дубликаты <strong>{duplicates}</strong></span>
                  <span>Очередь PDF <strong>{queued}</strong></span>
                  <span>Пропущено <strong>{skipped}</strong></span>
                </div>
                <div className="dashboard-job-footer">
                  <span>Старт: {formatDateTime(job.startedAt)}</span>
                  <span>Счётчик: {current}/{total || "—"}</span>
                  <span>Длительность: {formatDuration(elapsed)}</span>
                  <div className="actions-inline">
                    <button className="btn" type="button" onClick={() => onToggle(job.jobId)}>{isExpanded ? "Скрыть" : "Подробнее"}</button>
                    {job.status === "in_progress" && job.celeryStatus?.status !== "REVOKED" ? (
                      <button className="btn" type="button" onClick={() => onCancel(job.jobId)}>Остановить</button>
                    ) : (
                      <button className="btn btn-danger" type="button" onClick={() => onDelete(job.jobId)}>Удалить</button>
                    )}
                  </div>
                </div>
                {isExpanded && (
                  <div className="dashboard-job-details-card">
                    <div className="dashboard-job-details-grid">
                      <div><strong>Этап:</strong> {stage || "—"}</div>
                      <div><strong>Celery:</strong> {statusLabel(String(job.celeryStatus?.status || job.celeryStatus?.state || "UNKNOWN"))}</div>
                      <div><strong>Обновлено:</strong> {formatDateTime(job.lastCountChangeAt)}</div>
                      <div><strong>Наблюдалось записей:</strong> {job.lastObservedCount}</div>
                      {targetNew > 0 && <div><strong>Цель новых:</strong> {targetNew}</div>}
                      {candidateLimit > targetNew && <div><strong>Окно добора:</strong> до {candidateLimit} кандидатов</div>}
                      {examined > 0 && <div><strong>Проверено кандидатов:</strong> {examined}</div>}
                      {refillExhausted && <div><strong>Добор:</strong> доступные новые записи закончились</div>}
                    </div>
                    {taskIds.length > 0 && (
                      <details className="dashboard-task-id-details">
                        <summary>ID задач ({taskIds.length})</summary>
                        <div className="dashboard-task-id-list">
                          {taskIds.map((taskId) => <code key={taskId} title={taskId}>{shortTaskId(taskId)}</code>)}
                        </div>
                      </details>
                    )}
                    {perSourceRows.length > 0 && (
                      <div className="dashboard-source-mini-table">
                        {perSourceRows.map((row) => (
                          <Fragment key={`${job.jobId}:${row.name}`}>
                            <span>{row.name}</span>
                            <span className="status neutral">{statusLabel(row.status)}</span>
                            <span>сохр. {row.saved}</span>
                            <span>обн. {row.updated}</span>
                            <span>дубл. {row.duplicates}</span>
                            <span>{row.targetNew > 0 ? `пров. ${row.examined}/${row.targetNew} новых` : "—"}</span>
                            <span>{row.error || (row.refillExhausted ? "новые записи закончились" : "—")}</span>
                          </Fragment>
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
      )}
    </section>
  );
}
