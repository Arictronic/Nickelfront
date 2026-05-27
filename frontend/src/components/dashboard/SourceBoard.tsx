import type { DashboardSourceStatus } from "../../types/dashboard";

function statusClass(status: string | null): string {
  if (!status) return "neutral";
  if (["completed", "success", "SUCCESS", "ready", "ok"].includes(status)) return "active";
  if (["failed", "FAILURE", "error"].includes(status)) return "failed";
  if (["cancelled", "REVOKED", "revoked"].includes(status)) return "cancelled";
  if (["pending", "queued"].includes(status)) return "neutral";
  return "processing";
}

function statusLabel(status: string | null): string {
  if (!status) return "не запускался";
  const labels: Record<string, string> = {
    completed: "завершён",
    success: "успешно",
    SUCCESS: "успешно",
    ready: "готово",
    ok: "готово",
    failed: "ошибка",
    FAILURE: "ошибка",
    error: "ошибка",
    cancelled: "отменён",
    REVOKED: "отменён",
    revoked: "отменён",
    pending: "ожидает",
    queued: "в очереди",
    in_progress: "выполняется",
    STARTED: "выполняется",
    PROGRESS: "выполняется",
  };
  return labels[status] || status;
}

function percent(part: number, total: number): number {
  if (!total) return 0;
  return Math.round((part / total) * 100);
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)} с`;
  return `${Math.floor(seconds / 60)} мин ${Math.round(seconds % 60)} с`;
}

interface Props {
  sources: DashboardSourceStatus[];
}

export default function SourceBoard({ sources }: Props) {
  return (
    <section className="panel dashboard-source-board-panel">
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Парсеры</span>
          <h3>Источники данных</h3>
        </div>
      </div>
      <div className="dashboard-source-board">
        {sources.map((source) => {
          const fullTextPercent = percent(source.withFullText, source.papersCount);
          const embeddingPercent = percent(source.withEmbeddings, source.papersCount);
          return (
            <article key={source.name} className={`dashboard-source-tile ${source.enabled ? "enabled" : "disabled"}`}>
              <div className="dashboard-source-tile-head">
                <div>
                  <strong>{source.name}</strong>
                  <small>{source.kind} · лимит {source.limit || "—"}</small>
                </div>
                <span className={`status ${source.enabled ? "active" : "cancelled"}`}>{source.enabled ? "включён" : "отключён"}</span>
              </div>
              <div className="dashboard-source-tile-stats">
                <span><strong>{source.papersCount}</strong> документов</span>
                <span><strong>+{source.addedToday}</strong> сегодня</span>
                <span><strong>{fullTextPercent}%</strong> полный текст</span>
                <span><strong>{embeddingPercent}%</strong> эмбеддинги</span>
                <span><strong>{source.successRate ?? "—"}{source.successRate !== null ? "%" : ""}</strong> успешность</span>
                <span><strong>{formatDuration(source.lastDurationSec)}</strong> последний запуск</span>
              </div>
              <div className="dashboard-source-tile-footer">
                <span className={`status ${statusClass(source.lastStatus)}`}>{statusLabel(source.lastStatus)}</span>
                {source.errorRate !== null && source.errorRate > 0 && <span className="status warning">ошибок запусков: {source.errorRate}%</span>}
                {source.errors > 0 && <span className="status failed">ошибок данных: {source.errors}</span>}
              </div>
              {source.lastError && <p className="dashboard-source-error">{source.lastError}</p>}
            </article>
          );
        })}
      </div>
    </section>
  );
}
