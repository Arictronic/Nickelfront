import { Link } from "react-router-dom";
import type { DashboardActionName, DashboardActionPayload, DashboardRecommendedAction } from "../../types/dashboard";

interface Props {
  recommendedActions?: DashboardRecommendedAction[];
  runningAction?: string | null;
  actionStatus?: string | null;
  actionError?: string | null;
  onRunAction?: (action: DashboardActionName, payload?: DashboardActionPayload) => void;
}

function actionClass(kind: DashboardRecommendedAction["kind"]): string {
  if (kind === "error") return "danger";
  if (kind === "warning") return "warning";
  if (kind === "success") return "success";
  return "info";
}

const adminActions: Array<{
  name: DashboardActionName;
  label: string;
  hint: string;
  payload: DashboardActionPayload;
  confirm: string;
}> = [
  {
    name: "process_pdf_backlog",
    label: "Обработать очередь PDF",
    hint: "Поставить документы без полного текста и контент-блоков в очередь Celery",
    payload: { limit: 100, pdf_mode: "auto" },
    confirm: "Поставить до 100 документов в очередь обработки PDF/контента?",
  },
  {
    name: "retry_failed_content",
    label: "Повторить ошибки контента",
    hint: "Повторно поставить документы с ошибками PDF/Qwen/контента в очередь",
    payload: { limit: 100, pdf_mode: "auto" },
    confirm: "Повторить до 100 задач обработки контента с ошибками?",
  },
  {
    name: "rebuild_embeddings",
    label: "Добрать все эмбеддинги",
    hint: "Поставить все документы без эмбеддингов в очередь индексирования, без лимита",
    payload: {},
    confirm: "Поставить ВСЕ документы без эмбеддингов в очередь пересборки? Это может занять много времени.",
  },
  {
    name: "reindex_vector_store",
    label: "Синхронизировать Vector",
    hint: "Добавить/обновить в Vector index все документы с эмбеддингами из PostgreSQL, без очистки и без лимита",
    payload: {},
    confirm: "Синхронизировать Vector index со ВСЕМИ эмбеддингами из PostgreSQL?",
  },
  {
    name: "rebuild_vector_store_full",
    label: "Полная пересборка Vector",
    hint: "Очистить Vector index и заново добавить все документы с эмбеддингами из PostgreSQL",
    payload: {},
    confirm: "ВНИМАНИЕ: Vector index будет очищен и пересобран полностью по ВСЕМ эмбеддингам. Продолжить?",
  },
  {
    name: "rebuild_rag_index",
    label: "Пересобрать RAG/Chroma",
    hint: "Очистить RAG/Chroma и заново добавить весь готовый контент статей, без лимита",
    payload: {},
    confirm: "ВНИМАНИЕ: RAG/Chroma будет очищен и полностью пересобран по ВСЕМ готовым документам. Продолжить?",
  },
];

export default function QuickActionsPanel({
  recommendedActions = [],
  runningAction = null,
  actionStatus = null,
  actionError = null,
  onRunAction,
}: Props) {
  const runAction = (action: DashboardActionName, payload?: DashboardActionPayload, confirmation?: string) => {
    if (!onRunAction || runningAction) return;
    if (confirmation && !window.confirm(confirmation)) return;
    onRunAction(action, payload);
  };

  return (
    <section className="panel dashboard-actions-panel">
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Действия</span>
          <h3>Быстрые действия</h3>
        </div>
      </div>

      {actionStatus && <div className="dashboard-action-status success">{actionStatus}</div>}
      {actionError && <div className="dashboard-action-status danger">{actionError}</div>}

      {recommendedActions.length > 0 && (
        <div className="dashboard-recommended-actions">
          <strong>Что исправить первым</strong>
          {recommendedActions.slice(0, 3).map((action) => {
            if (action.actionName) {
              const running = runningAction === action.actionName;
              return (
                <button
                  key={`${action.title}:${action.actionName}`}
                  type="button"
                  className={`dashboard-recommended-action ${actionClass(action.kind)}`}
                  disabled={Boolean(runningAction)}
                  onClick={() => runAction(action.actionName!, action.actionPayload || undefined, `${action.title}?`)}
                >
                  <span>{action.title}</span>
                  <small>{action.description}</small>
                  <em>{running ? "Запускаю…" : action.actionLabel}</em>
                </button>
              );
            }
            return (
              <Link key={`${action.title}:${action.actionTo}`} to={action.actionTo} className={`dashboard-recommended-action ${actionClass(action.kind)}`}>
                <span>{action.title}</span>
                <small>{action.description}</small>
                <em>{action.actionLabel}</em>
              </Link>
            );
          })}
        </div>
      )}

      <div className="dashboard-admin-actions">
        <strong>Админ-действия</strong>
        <div className="dashboard-admin-action-grid">
          {adminActions.map((action) => {
            const running = runningAction === action.name;
            return (
              <button
                key={action.name}
                type="button"
                className="dashboard-admin-action"
                disabled={Boolean(runningAction)}
                onClick={() => runAction(action.name, action.payload, action.confirm)}
              >
                <span>{action.label}</span>
                <small>{action.hint}</small>
                <em>{running ? "Запускаю…" : "Запустить"}</em>
              </button>
            );
          })}
        </div>
      </div>

    </section>
  );
}
