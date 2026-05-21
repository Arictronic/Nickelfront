import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getAlloyAnalysisPrompt,
  getAlloyAnalysisResults,
  getCeleryTaskStatus,
  saveAlloyAnalysisPrompt,
  startAlloyBatchAnalysis,
  type CeleryTaskStatus,
} from "../api/papers";
import { PAPER_SOURCES } from "../types/paper";

type AlloyBatchPaperResult = {
  paper_id: number;
  paper_title: string;
  source: string;
  text_length: number;
  chunks_total: number;
  items_count: number;
  warnings_count: number;
  summary_path: string;
  chunk_files: string[];
  extraction?: {
    extraction_metadata?: {
      total_alloys_found?: number;
      warnings?: string[];
    };
    items?: any[];
  };
  error?: string | null;
  updated_at?: string;
};

type AlloyBatchTaskResult = {
  status?: string;
  id_spec?: string | null;
  sources?: string[];
  total?: number;
  current?: number;
  paper_id?: number;
  paper_title?: string;
  stage?: string;
  stage_label?: string;
  chunks?: number;
  current_chunk?: number;
  processed_chunks?: number;
  total_chunks?: number;
  processed?: number;
  results?: AlloyBatchPaperResult[];
  results_dir?: string;
};

type StoredAlloyTask = {
  taskId: string;
  startedAt: number;
  idSpec: string;
  sources: string[];
  limit: number;
  taskStatus?: CeleryTaskStatus;
};

const ACTIVE_ALLOY_TASK_KEY = "alloyAnalysis.activeTask.v1";
const ACTIVE_ALLOY_TASK_MAX_AGE_MS = 8 * 60 * 60_000;
const STALE_PENDING_ALLOY_TASK_MS = 30 * 60_000;

function clearActiveAlloyTask() {
  localStorage.removeItem(ACTIVE_ALLOY_TASK_KEY);
}

function loadActiveAlloyTask(): StoredAlloyTask | null {
  try {
    const raw = localStorage.getItem(ACTIVE_ALLOY_TASK_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredAlloyTask;
    if (
      parsed?.startedAt &&
      Date.now() - parsed.startedAt > ACTIVE_ALLOY_TASK_MAX_AGE_MS
    ) {
      clearActiveAlloyTask();
      return null;
    }
    return parsed?.taskId ? parsed : null;
  } catch {
    clearActiveAlloyTask();
    return null;
  }
}

function saveActiveAlloyTask(task: StoredAlloyTask) {
  localStorage.setItem(ACTIVE_ALLOY_TASK_KEY, JSON.stringify(task));
}

function taskIsFinished(status?: string) {
  return status === "SUCCESS" || status === "FAILURE" || status === "REVOKED";
}

function hasTaskProgress(status: CeleryTaskStatus | null | undefined) {
  const progress = status?.result ?? status?.progress ?? {};
  const current = Number(
    progress.current || progress.processed || progress.processed_chunks || 0,
  );
  return current > 0 || status?.status === "STARTED";
}

function formatNumber(value: number | undefined | null) {
  return Number(value || 0).toLocaleString("ru-RU");
}

function normalizeLimit(value: unknown) {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.min(1000, Math.floor(parsed)));
}

const scrollBoxStyle = {
  width: "100%",
  maxHeight: 420,
  overflow: "auto",
  border: "1px solid var(--border)",
  borderRadius: 12,
  background: "var(--surface-2)",
  padding: 14,
} as const;

const sourceLabelStyle = {
  color: "var(--muted)",
  fontSize: 12,
  marginTop: 4,
} as const;

function prettifyValue(value: unknown) {
  if (value === null || value === undefined) return "не указано";
  if (typeof value === "number")
    return Number.isInteger(value)
      ? String(value)
      : value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  if (typeof value === "string") return value || "не указано";
  return JSON.stringify(value);
}

function propertySummary(alloy: any) {
  const physical = Object.keys(alloy?.properties?.physical || {}).length;
  const mechanical = Object.keys(alloy?.properties?.mechanical || {}).length;
  const highTemperature = Object.keys(
    alloy?.properties?.high_temperature || {},
  ).length;
  const total = physical + mechanical + highTemperature;
  if (!total) return "Свойства не извлечены";
  return `Свойства: физические ${physical}, механические ${mechanical}, высокотемпературные ${highTemperature}`;
}

export default function AlloyAnalysis() {
  const [idSpec, setIdSpec] = useState("");
  const [limit, setLimit] = useState(100);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<CeleryTaskStatus | null>(null);
  const [savedResults, setSavedResults] = useState<AlloyBatchPaperResult[]>([]);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [promptDraft, setPromptDraft] = useState("");
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [promptMessage, setPromptMessage] = useState<string | null>(null);

  const taskResult = (taskStatus?.result ??
    null) as AlloyBatchTaskResult | null;
  const results = taskResult?.results?.length
    ? taskResult.results
    : savedResults;
  const running =
    submitting || (!!taskId && !taskIsFinished(taskStatus?.status));

  useEffect(() => {
    const restoredTask = loadActiveAlloyTask();
    if (restoredTask) {
      setTaskId(restoredTask.taskId);
      setTaskStatus(
        restoredTask.taskStatus || {
          task_id: restoredTask.taskId,
          status: "PENDING",
          state: "PENDING",
        },
      );
      setIdSpec(restoredTask.idSpec || "");
      setSelectedSources(
        Array.isArray(restoredTask.sources) ? restoredTask.sources : [],
      );
      setLimit(restoredTask.limit || 100);
    }
    void loadSavedResults();
    void loadPrompt();
  }, []);

  useEffect(() => {
    if (!taskId) return;
    if (taskIsFinished(taskStatus?.status)) {
      clearActiveAlloyTask();
      return;
    }
    saveActiveAlloyTask({
      taskId,
      startedAt: loadActiveAlloyTask()?.startedAt || Date.now(),
      idSpec,
      sources: selectedSources,
      limit,
      taskStatus: taskStatus || undefined,
    });
  }, [idSpec, limit, selectedSources, taskId, taskStatus]);

  useEffect(() => {
    if (!taskId || taskIsFinished(taskStatus?.status)) return;

    let cancelled = false;

    const poll = async () => {
      try {
        const status = await getCeleryTaskStatus(taskId);
        if (!cancelled) {
          const stored = loadActiveAlloyTask();
          const isStalePending =
            status.status === "PENDING" &&
            !!stored?.startedAt &&
            Date.now() - stored.startedAt > STALE_PENDING_ALLOY_TASK_MS &&
            !hasTaskProgress(status);

          if (isStalePending) {
            clearActiveAlloyTask();
            setTaskId(null);
            setTaskStatus(null);
            setError(
              "Старая задача анализа не найдена в Celery/Redis и очищена из интерфейса.",
            );
            return;
          }

          setTaskStatus(status);
          if (taskIsFinished(status.status)) {
            clearActiveAlloyTask();
          }
        }
      } catch (e) {
        if (!cancelled) {
          const statusCode = (e as any)?.response?.status;
          if (statusCode === 404) {
            clearActiveAlloyTask();
            setTaskId(null);
            setTaskStatus(null);
          }
          setError((e as Error).message);
        }
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), 5000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [taskId, taskStatus?.status]);

  useEffect(() => {
    if (taskStatus?.status === "SUCCESS") {
      void loadSavedResults();
    }
  }, [taskStatus?.status]);

  const loadSavedResults = async () => {
    setLoadingSaved(true);
    try {
      const loaded = await getAlloyAnalysisResults(200);
      setSavedResults(loaded);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingSaved(false);
    }
  };

  const loadPrompt = async () => {
    try {
      const loaded = await getAlloyAnalysisPrompt();
      setPrompt(loaded);
      setPromptDraft(loaded);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const savePrompt = async () => {
    setSavingPrompt(true);
    setPromptMessage(null);
    try {
      const saved = await saveAlloyAnalysisPrompt(promptDraft);
      setPrompt(saved.prompt);
      setPromptDraft(saved.prompt);
      setEditingPrompt(false);
      setPromptMessage(
        "Промпт сохранён. Новые задачи будут использовать эту версию.",
      );
    } catch (e) {
      setPromptMessage(`Ошибка сохранения: ${(e as Error).message}`);
    } finally {
      setSavingPrompt(false);
    }
  };

  const renderAlloyCards = (item: AlloyBatchPaperResult) => {
    const alloys = item.extraction?.items ?? [];
    if (!Array.isArray(alloys) || alloys.length === 0) {
      const warnings = item.extraction?.extraction_metadata?.warnings || [];
      return (
        <div>
          <p className="muted">Сплавы не извлечены по текущей схеме.</p>
          {Array.isArray(warnings) && warnings.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <strong>Почему:</strong>
              <ul
                style={{
                  margin: "8px 0 0 18px",
                  color: "var(--muted)",
                  lineHeight: 1.45,
                }}
              >
                {warnings.slice(0, 5).map((warning: string, index: number) => (
                  <li key={`${item.paper_id}-warning-${index}`}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      );
    }

    return (
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 12,
        }}
      >
        {alloys.slice(0, 8).map((alloy: any, index: number) => {
          const composition = alloy?.chemical_composition || {};
          const elements = Object.entries(composition).slice(0, 8);
          const notes = [
            ...(Array.isArray(alloy?.applications) ? alloy.applications : []),
            ...(Array.isArray(alloy?.quality_flags?.conflicting_properties)
              ? alloy.quality_flags.conflicting_properties.map(
                  (p: string) => `Конфликт: ${p}`,
                )
              : []),
          ].filter(Boolean);
          return (
            <div
              key={`${alloy?.alloy_name || "alloy"}-${index}`}
              className="panel"
              style={{
                boxShadow: "none",
                borderRadius: 18,
                background:
                  "linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 10,
                  alignItems: "flex-start",
                }}
              >
                <div>
                  <h3
                    style={{
                      color: "var(--text)",
                      fontSize: 17,
                      marginBottom: 4,
                    }}
                  >
                    {alloy?.alloy_name || "Сплав без названия"}
                  </h3>
                  <p style={sourceLabelStyle}>
                    {alloy?.alloy_class || "Класс не указан"}
                  </p>
                </div>
                <span className="counter-badge">{elements.length} эл.</span>
              </div>
              {alloy?.processing_state && (
                <p style={{ margin: "12px 0 0", lineHeight: 1.45 }}>
                  <strong>Состояние:</strong> {alloy.processing_state}
                </p>
              )}
              {elements.length > 0 && (
                <div className="filters" style={{ marginTop: 10 }}>
                  {elements.map(([element, value]) => (
                    <span key={element} className="counter-badge">
                      {element}: {prettifyValue(value)}
                    </span>
                  ))}
                </div>
              )}
              <p className="muted" style={{ marginTop: 10 }}>
                {propertySummary(alloy)}
              </p>
              {Array.isArray(alloy?.standards) &&
                alloy.standards.length > 0 && (
                  <p className="muted" style={{ marginTop: 10 }}>
                    Стандарты: {alloy.standards.join(", ")}
                  </p>
                )}
              {notes.length > 0 && (
                <div
                  style={{
                    marginTop: 10,
                    borderTop: "1px solid var(--border)",
                    paddingTop: 10,
                  }}
                >
                  {notes.slice(0, 3).map((note: string, noteIndex: number) => (
                    <p
                      key={`${note}-${noteIndex}`}
                      className="muted"
                      style={{ marginTop: noteIndex ? 6 : 0 }}
                    >
                      {note}
                    </p>
                  ))}
                </div>
              )}
              {alloy?.source_text_snippet && (
                <details style={{ marginTop: 10 }}>
                  <summary className="muted" style={{ cursor: "pointer" }}>
                    Фрагмент источника
                  </summary>
                  <p style={{ marginTop: 8, lineHeight: 1.45 }}>
                    {alloy.source_text_snippet}
                  </p>
                </details>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  const metrics = useMemo(() => {
    return results.reduce(
      (acc, item) => {
        acc.articles += 1;
        acc.chunks += item.chunks_total || 0;
        acc.alloys += item.items_count || 0;
        acc.warnings += item.warnings_count || 0;
        acc.textLength += item.text_length || 0;
        if (item.error) acc.errors += 1;
        return acc;
      },
      {
        articles: 0,
        chunks: 0,
        alloys: 0,
        warnings: 0,
        textLength: 0,
        errors: 0,
      },
    );
  }, [results]);

  const progress = taskStatus?.result || taskStatus?.progress || {};
  const currentArticle = Number(progress.current || 0);
  const totalArticles = Number(progress.total || 0);
  const currentChunk = Number(progress.current_chunk || 0);
  const articleChunks = Number(progress.chunks || 0);
  const processedChunks = Number(progress.processed_chunks || 0);
  const totalChunks = Number(progress.total_chunks || 0);
  const stageLabel = String(
    progress.stage_label || progress.stage || taskStatus?.status || "Ожидание",
  );
  const progressPercent =
    totalChunks > 0
      ? Math.round((processedChunks / totalChunks) * 100)
      : totalArticles > 0
        ? Math.round((currentArticle / totalArticles) * 100)
        : 0;
  const progressText =
    totalArticles > 0
      ? `${currentArticle} / ${totalArticles}`
      : taskStatus?.status || "Ожидает запуска";

  const toggleSource = (source: string) => {
    setSelectedSources((prev) =>
      prev.includes(source)
        ? prev.filter((item) => item !== source)
        : [...prev, source],
    );
  };

  const runAnalysis = async () => {
    const safeLimit = normalizeLimit(limit);
    setLimit(safeLimit);
    setSubmitting(true);
    setError(null);
    setTaskId(null);
    setTaskStatus(null);
    setSavedResults([]);

    try {
      const queued = await startAlloyBatchAnalysis({
        idSpec: idSpec.trim() || undefined,
        sources: selectedSources,
        limit: safeLimit,
      });
      saveActiveAlloyTask({
        taskId: queued.task_id,
        startedAt: Date.now(),
        idSpec,
        sources: selectedSources,
        limit: safeLimit,
      });
      setTaskId(queued.task_id);
      setTaskStatus({
        task_id: queued.task_id,
        status: "PENDING",
        state: "PENDING",
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Анализ сплавов</h2>
          <p className="muted" style={{ marginTop: 6 }}>
            Пакетный анализ статей с полным текстом: воркер режет текст на части
            до 40 000 символов, сохраняет JSON по чанкам и собирает итог по
            статье.
          </p>
        </div>
        <div className="actions">
          <button
            className="btn"
            onClick={() => void loadSavedResults()}
            disabled={loadingSaved}
          >
            {loadingSaved ? "Загрузка..." : "Обновить результаты"}
          </button>
          <button
            className="btn btn-primary"
            onClick={runAnalysis}
            disabled={running}
          >
            {running ? "Анализ выполняется..." : "Запустить анализ"}
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Выбор статей</h3>
        <div className="filters">
          <input
            className="input"
            value={idSpec}
            onChange={(e) => setIdSpec(e.target.value)}
            placeholder="ID или диапазоны: 1-20, 35, 40-45"
            style={{ minWidth: 320 }}
          />
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span>Лимит:</span>
            <input
              className="input"
              type="number"
              min={1}
              max={1000}
              value={limit}
              onChange={(e) => setLimit(normalizeLimit(e.target.value))}
              style={{ width: 110 }}
            />
          </label>
          {taskId && <span className="counter-badge">task_id: {taskId}</span>}
          {taskStatus && (
            <span className="counter-badge">статус: {taskStatus.status}</span>
          )}
          {running && (
            <span className="counter-badge">прогресс: {progressText}</span>
          )}
        </div>
        <p className="muted" style={{ marginTop: 8 }}>
          Если диапазон ID пустой, будут взяты первые статьи с полным текстом по
          выбранным источникам и лимиту.
        </p>

        <div className="filters" style={{ marginTop: 14 }}>
          {PAPER_SOURCES.map((source) => (
            <label
              key={source}
              className="counter-badge"
              style={{ cursor: "pointer" }}
            >
              <input
                type="checkbox"
                checked={selectedSources.includes(source)}
                onChange={() => toggleSource(source)}
                style={{ marginRight: 8 }}
              />
              {source}
            </label>
          ))}
        </div>
      </div>

      <div className="panel" style={{ overflow: "hidden" }}>
        <div
          className="page-head"
          style={{ alignItems: "flex-start", gap: 12 }}
        >
          <div>
            <h3>Промпт анализа</h3>
            <p className="muted">
              Этот текст использует Celery worker для новых задач анализа.
              Сейчас:{" "}
              {formatNumber((editingPrompt ? promptDraft : prompt).length)}{" "}
              символов.
            </p>
          </div>
          <div className="actions">
            {editingPrompt ? (
              <>
                <button
                  className="btn"
                  onClick={() => {
                    setPromptDraft(prompt);
                    setEditingPrompt(false);
                  }}
                  disabled={savingPrompt}
                >
                  Отмена
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => void savePrompt()}
                  disabled={savingPrompt}
                >
                  {savingPrompt ? "Сохранение..." : "Сохранить"}
                </button>
              </>
            ) : (
              <button className="btn" onClick={() => setEditingPrompt(true)}>
                Изменить
              </button>
            )}
          </div>
        </div>
        {editingPrompt ? (
          <div style={scrollBoxStyle}>
            <textarea
              className="input"
              value={promptDraft}
              onChange={(e) => setPromptDraft(e.target.value)}
              rows={18}
              style={{
                width: "100%",
                minHeight: 320,
                resize: "vertical",
                fontFamily: "Consolas, Courier New, monospace",
                lineHeight: 1.5,
                whiteSpace: "pre-wrap",
              }}
            />
          </div>
        ) : (
          <pre
            className="markdown-body"
            style={{
              ...scrollBoxStyle,
              whiteSpace: "pre-wrap",
              overflowWrap: "anywhere",
              margin: 0,
              fontFamily: "Consolas, Courier New, monospace",
              lineHeight: 1.5,
            }}
          >
            {prompt || "Промпт загружается..."}
          </pre>
        )}
        {promptMessage && (
          <p
            className={promptMessage.startsWith("Ошибка") ? "error" : "muted"}
            style={{ marginTop: 10 }}
          >
            {promptMessage}
          </p>
        )}
      </div>

      {error && <p className="error">{error}</p>}

      {taskStatus && (
        <div className="panel">
          <h3>Статус анализа</h3>
          <div className="detail-grid">
            <div>
              <strong>Этап:</strong> {stageLabel}
            </div>
            <div>
              <strong>Статус Celery:</strong> {taskStatus.status}
            </div>
            <div>
              <strong>Статьи:</strong> {progressText}
            </div>
            <div>
              <strong>Части текста:</strong> {processedChunks} /{" "}
              {totalChunks || "?"}
            </div>
            <div>
              <strong>Текущая статья:</strong>{" "}
              {progress.paper_id ? (
                <Link
                  className="action-link"
                  to={`/papers/${progress.paper_id}`}
                >
                  #{progress.paper_id}
                </Link>
              ) : (
                "—"
              )}
            </div>
            <div>
              <strong>Текущая часть:</strong> {currentChunk || 0} /{" "}
              {articleChunks || "?"}
            </div>
          </div>
          {progress.paper_title && (
            <p className="muted" style={{ marginTop: 10 }}>
              {String(progress.paper_title)}
            </p>
          )}
          <div
            style={{
              marginTop: 12,
              height: 10,
              background: "var(--surface-2)",
              borderRadius: 999,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${Math.max(3, Math.min(100, progressPercent))}%`,
                height: "100%",
                background: "var(--primary)",
                transition: "width 0.2s ease",
              }}
            />
          </div>
          <p className="muted" style={{ marginTop: 8 }}>
            Прогресс примерно: {progressPercent}%
          </p>
        </div>
      )}

      {taskStatus?.status === "FAILURE" && (
        <div className="panel">
          <p className="error">
            Задача завершилась ошибкой. Подробности смотри в логах Celery
            worker.
          </p>
        </div>
      )}

      <div className="kpi-grid">
        <div className="panel kpi-card">
          <h3>Статей обработано</h3>
          <div className="kpi">{formatNumber(metrics.articles)}</div>
        </div>
        <div className="panel kpi-card">
          <h3>Чанков текста</h3>
          <div className="kpi">{formatNumber(metrics.chunks)}</div>
        </div>
        <div className="panel kpi-card">
          <h3>Извлечено сплавов</h3>
          <div className="kpi">{formatNumber(metrics.alloys)}</div>
        </div>
        <div className="panel kpi-card">
          <h3>Ошибок</h3>
          <div
            className="kpi"
            style={{ color: metrics.errors ? "#ef4444" : undefined }}
          >
            {formatNumber(metrics.errors)}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>Результаты по статьям</h3>
        {results.length === 0 ? (
          <p className="muted">
            {running
              ? "Воркер анализирует выбранные статьи. Результаты появятся после завершения задачи."
              : "Сохранённых результатов пока нет. Запустите анализ или нажмите «Обновить результаты»."}
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Статья</th>
                <th>Источник</th>
                <th>Символов</th>
                <th>Чанков</th>
                <th>Сплавов</th>
                <th>JSON</th>
                <th>Обновлено</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {results.map((item) => (
                <tr key={item.paper_id}>
                  <td>{item.paper_id}</td>
                  <td style={{ maxWidth: 520 }}>
                    <Link
                      className="action-link"
                      to={`/papers/${item.paper_id}`}
                    >
                      Открыть
                    </Link>
                    <div style={{ fontWeight: 700, marginTop: 8 }}>
                      {item.paper_title}
                    </div>
                  </td>
                  <td>{item.source}</td>
                  <td>{formatNumber(item.text_length)}</td>
                  <td>{item.chunks_total}</td>
                  <td>{item.items_count}</td>
                  <td style={{ fontSize: 12 }}>
                    <div className="muted">summary: {item.summary_path}</div>
                    <div className="muted">
                      chunks: {item.chunk_files?.length || 0}
                    </div>
                  </td>
                  <td>
                    {item.updated_at
                      ? new Date(item.updated_at).toLocaleString()
                      : "—"}
                  </td>
                  <td>
                    {item.error ? (
                      <span className="error">{item.error}</span>
                    ) : (
                      "Готово"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {results.length > 0 && (
        <div className="panel">
          <h3>Карточки извлечённых данных</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {results.map((item) => (
              <article
                key={`cards-${item.paper_id}`}
                className="panel"
                style={{
                  boxShadow: "none",
                  borderRadius: 20,
                  borderColor: item.items_count ? "#bfd3ea" : "var(--border)",
                }}
              >
                <div className="page-head" style={{ gap: 12 }}>
                  <div>
                    <h3 style={{ color: "var(--text)", fontSize: 18 }}>
                      #{item.paper_id} {item.paper_title}
                    </h3>
                    <p className="muted">
                      {item.source} · {formatNumber(item.text_length)} символов
                      · чанков: {item.chunks_total} · сплавов:{" "}
                      {item.items_count}
                    </p>
                  </div>
                  <div className="actions">
                    <span
                      className={`status ${item.items_count ? "active" : ""}`}
                    >
                      {item.items_count ? "Есть данные" : "Нет сплавов"}
                    </span>
                    <Link
                      className="action-link"
                      to={`/papers/${item.paper_id}`}
                    >
                      Открыть статью
                    </Link>
                  </div>
                </div>
                {renderAlloyCards(item)}
              </article>
            ))}
          </div>
        </div>
      )}

      {results.length > 0 && (
        <div className="panel">
          <h3>
            {taskResult?.results?.length
              ? "Сводный JSON последней задачи"
              : "Сводный JSON сохранённых результатов"}
          </h3>
          <pre
            className="markdown-body"
            style={{
              ...scrollBoxStyle,
              maxHeight: 520,
              whiteSpace: "pre-wrap",
              overflowWrap: "anywhere",
              margin: 0,
              fontFamily: "Consolas, Courier New, monospace",
            }}
          >
            {JSON.stringify(
              taskResult?.results?.length ? taskResult : { results },
              null,
              2,
            )}
          </pre>
        </div>
      )}
    </div>
  );
}
