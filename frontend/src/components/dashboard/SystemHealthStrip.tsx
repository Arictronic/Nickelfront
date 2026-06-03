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
  vector: "Векторный индекс",
  rag: "RAG-индекс",
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
  if (name === "rag") {
    const ready = service.ready ?? 0;
    const candidates = service.candidates ?? 0;
    const chunks = service.indexed ?? service.count ?? 0;
    if (service.ids_status === "unknown") return `чанков ${chunks} · проверка статей недоступна`;
    if (candidates > 0) return `статей ${ready}/${candidates} · чанков ${chunks}`;
    if (chunks > 0) return `чанков в индексе ${chunks}`;
    return service.index_status === "empty" ? "индекс пуст" : null;
  }
  if (name === "vector" && service.indexed !== undefined) {
    if (service.ids_status === "unknown") return `записей ${service.indexed ?? service.count ?? 0} · проверка статей недоступна`;
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
