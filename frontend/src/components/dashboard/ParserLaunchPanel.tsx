import type { PaperSource, PdfProcessingMode } from "../../types/paper";
import type { ParserSettings } from "../../types/settings";

export type SourceGuidance = {
  method: "API" | "HTML";
  short: string;
};

const PRESETS = [
  "nickel-based superalloys",
  "heat resistant nickel alloys",
  "nickel alloy creep oxidation",
  "patent nickel superalloy turbine blade",
  "titanium alloys aerospace",
  "cobalt based superalloys",
  "aluminum lithium alloys",
  "magnesium alloys corrosion",
  "copper alloys electrical conductivity",
  "stainless steel heat resistance",
  "refractory high entropy alloys",
  "zirconium alloys nuclear materials",
];

const PDF_MODE_LABELS: Record<PdfProcessingMode, string> = {
  auto: "Авто: PDF и текст",
  ai: "AI-анализ PDF",
  mypdf: "MyPDF — быстрый текст",
};

interface Props {
  query: string;
  source: PaperSource | "all";
  limit: number;
  pdfMode: PdfProcessingMode;
  sources: readonly PaperSource[];
  enabledSources: PaperSource[];
  parserSettings: ParserSettings | null;
  sourceGuidance: Record<PaperSource | "all", SourceGuidance>;
  selectedSourceDisabled: boolean;
  sourceLimit: number;
  startingParse: boolean;
  isAdmin: boolean;
  error: string | null;
  onQueryChange: (query: string) => void;
  onSourceChange: (source: PaperSource | "all") => void;
  onLimitChange: (limit: number) => void;
  onPdfModeChange: (mode: PdfProcessingMode) => void;
  onStart: () => void;
}

function clampLimit(value: unknown): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.min(100, Math.floor(parsed)));
}

export default function ParserLaunchPanel({
  query,
  source,
  limit,
  pdfMode,
  sources,
  enabledSources,
  parserSettings,
  sourceGuidance,
  selectedSourceDisabled,
  sourceLimit,
  startingParse,
  isAdmin,
  error,
  onQueryChange,
  onSourceChange,
  onLimitChange,
  onPdfModeChange,
  onStart,
}: Props) {
  const guidance = sourceGuidance[source];
  const effectiveLimit = Math.min(limit, sourceLimit || 100);
  const parserDisabled = parserSettings?.enabled === false;
  const launchDisabled = startingParse || selectedSourceDisabled || parserDisabled || !isAdmin;
  return (
    <section className="panel dashboard-launch-panel">
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Основной сценарий</span>
          <h3>Запуск сбора</h3>
        </div>
        <span className={`status ${parserDisabled ? "failed" : "active"}`}>
          {parserDisabled ? "Парсинг отключён" : isAdmin ? "Парсинг доступен" : "Только админ"}
        </span>
      </div>

      <div className="dashboard-launch-query">
        <label>
          Поисковый запрос
          <input
            className="input"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Например: nickel-based superalloys"
          />
        </label>
        <button
          className="btn btn-primary dashboard-launch-button"
          type="button"
          onClick={onStart}
          disabled={launchDisabled}
          title={!isAdmin ? "Запуск парсинга доступен только администратору" : undefined}
        >
          {startingParse ? "Запускаю..." : isAdmin ? "Запустить" : "Только админ"}
        </button>
      </div>

      <div className="dashboard-launch-controls">
        <label>
          Источник
          <select value={source} onChange={(event) => onSourceChange(event.target.value as PaperSource | "all")}>
            <option value="all" disabled={enabledSources.length === 0}>Все включённые источники</option>
            {sources.map((src) => (
              <option key={src} value={src} disabled={parserSettings?.enabled_sources?.[src] === false}>
                {src}{parserSettings?.enabled_sources?.[src] === false ? " — отключён" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Лимит
          <input
            className="input"
            type="number"
            min={1}
            max={sourceLimit || 100}
            value={limit}
            onChange={(event) => onLimitChange(clampLimit(event.target.value))}
          />
        </label>
        <label>
          Режим обработки PDF
          <select value={pdfMode} onChange={(event) => onPdfModeChange(event.target.value as PdfProcessingMode)}>
            <option value="auto">{PDF_MODE_LABELS.auto}</option>
            <option value="mypdf">{PDF_MODE_LABELS.mypdf}</option>
            <option value="ai">{PDF_MODE_LABELS.ai}</option>
          </select>
        </label>
      </div>

      <div className="dashboard-presets">
        <span>Быстрые пресеты:</span>
        {PRESETS.map((preset) => (
          <button key={preset} type="button" className="chip-button" onClick={() => onQueryChange(preset)}>
            {preset}
          </button>
        ))}
      </div>

      <div className="dashboard-source-context">
        <div>
          <strong>{source === "all" ? "Все источники" : source}</strong>
          <p>{guidance?.short || "Источник будет обработан через backend-парсер."}</p>
        </div>
        <div className="dashboard-source-facts">
          <span className="status neutral">{guidance?.method || "API"}</span>
          <span>{source === "all" ? `лимит на источник ${effectiveLimit}` : `лимит источника ${effectiveLimit}`}</span>
          <span>источников включено: {enabledSources.length}</span>
        </div>
      </div>

      {source === "all" && (
        <p className="dashboard-inline-warning">
          Будет создана тяжёлая Celery-задача по всем включённым источникам. Лимит применяется к каждому источнику отдельно.
        </p>
      )}
      {!isAdmin && (
        <p className="dashboard-inline-warning">
          Запуск парсинга и массовых задач доступен только администратору. Просмотр статей, PDF, статусов и истории остаётся доступен.
        </p>
      )}
      {selectedSourceDisabled && <p className="error">Источник отключён в технических настройках.</p>}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
