import { Link } from "react-router-dom";
import type { DashboardDiagnostic, DashboardLoadError } from "../../types/dashboard";

const LEVEL_LABELS: Record<DashboardDiagnostic["level"], string> = {
  success: "ОК",
  info: "Инфо",
  warning: "Внимание",
  error: "Ошибка",
};

interface Props {
  diagnostics: DashboardDiagnostic[];
  loadErrors: DashboardLoadError[];
}

export default function DiagnosticsPanel({ diagnostics, loadErrors }: Props) {
  const apiDiagnostics: DashboardDiagnostic[] = loadErrors.map((error) => ({
    level: "error",
    title: error.label,
    message: error.message,
  }));
  const items = [...apiDiagnostics, ...diagnostics].slice(0, 8);

  return (
    <section className="panel dashboard-diagnostics-panel">
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Диагностика</span>
          <h3>Проблемы и рекомендации</h3>
        </div>
        <span className={`status ${items.some((item) => item.level === "error") ? "failed" : items.some((item) => item.level === "warning") ? "warning" : "active"}`}>
          {items.length} сигналов
        </span>
      </div>
      <div className="dashboard-diagnostics-list">
        {items.length === 0 ? (
          <p className="muted">Диагностика пока пустая.</p>
        ) : items.map((item, index) => (
          <article key={`${item.title}:${index}`} className={`dashboard-diagnostic-item ${item.level}`}>
            <span>{LEVEL_LABELS[item.level]}</span>
            <div>
              <strong>{item.title}</strong>
              <p>{item.message}</p>
              {item.actionTo && item.actionLabel && <Link to={item.actionTo}>{item.actionLabel} →</Link>}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
