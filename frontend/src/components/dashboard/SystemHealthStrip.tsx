import type { DashboardServiceStatus } from "../../types/dashboard";

const STATUS_LABELS: Record<string, string> = {
  online: "доступен",
  offline: "недоступен",
  warning: "требует внимания",
  unknown: "неизвестно",
};

const SERVICE_LABELS: Record<string, string> = {
  backend: "FastAPI",
  database: "PostgreSQL",
  redis: "Redis",
  celery: "Celery",
  qwen: "Qwen",
  vector: "Vector",
  rag: "RAG/Chroma",
};

function statusClass(status: string | undefined): string {
  if (status === "online") return "success";
  if (status === "offline") return "error";
  if (status === "warning") return "warning";
  return "unknown";
}

function detailText(name: string, service: DashboardServiceStatus): string | null {
  if (name === "celery") {
    const workers = service.workers ?? 0;
    const active = service.active ?? 0;
    const queued = service.queued ?? 0;
    if (workers <= 0) {
      return service.reason || service.error || "статус уточняется; worker мог быть занят";
    }
    return `${workers} воркеров · активных ${active} · в очереди ${queued}`;
  }
  if (name === "redis" && service.memory) return `память ${service.memory}`;
  if ((name === "vector" || name === "rag") && service.indexed !== undefined) {
    return `в индексе ${service.indexed ?? service.count ?? 0}`;
  }
  if (name === "qwen") {
    if (service.reason) return String(service.reason);
    return service.model ? `модель ${service.model}` : "модель не указана";
  }
  if (service.model) return `модель ${service.model}`;
  if (service.path) return String(service.path);
  if (service.error) return String(service.error);
  return null;
}

interface Props {
  services: Record<string, DashboardServiceStatus>;
}

export default function SystemHealthStrip({ services }: Props) {
  const ordered = ["backend", "database", "redis", "celery", "qwen", "vector", "rag"];
  return (
    <section className="dashboard-health-strip" aria-label="Состояние сервисов">
      {ordered.map((name) => {
        const service = services[name] || { status: "unknown", label: SERVICE_LABELS[name] || name };
        const detail = detailText(name, service);
        const statusLabel = STATUS_LABELS[service.status] || service.status || "неизвестно";
        return (
          <article key={name} className={`dashboard-health-item ${statusClass(service.status)}`} title={detail || undefined}>
            <span className="dashboard-health-dot" />
            <div>
              <strong>{SERVICE_LABELS[name] || service.label || name}</strong>
              <small>{statusLabel}{detail ? ` · ${detail}` : ""}</small>
            </div>
          </article>
        );
      })}
    </section>
  );
}
