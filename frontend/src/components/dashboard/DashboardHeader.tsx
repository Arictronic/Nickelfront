interface Props {
  generatedAt?: string | null;
  onRefresh: () => void;
  refreshing: boolean;
}

function formatGeneratedAt(value?: string | null): string {
  if (!value) return "нет данных";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "нет данных";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function DashboardHeader({ generatedAt, onRefresh, refreshing }: Props) {
  return (
    <section className="dashboard-hero">
      <div className="dashboard-hero-main">
        <span className="eyebrow">Nickelfront · операционный центр</span>
        <h2>Главная панель сбора и готовности данных</h2>
        <p>
          Управление парсерами, очередями обработки PDF и контента, качеством базы и готовностью RAG/Qwen.
        </p>
      </div>
      <div className="dashboard-hero-actions">
        <button className="btn" type="button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Обновляю…" : "Обновить всё"}
        </button>
        <div className="dashboard-hero-refresh-meta">Ответ от сервера: {formatGeneratedAt(generatedAt)}</div>
      </div>
    </section>
  );
}
