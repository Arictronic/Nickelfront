import { useEffect, useMemo, useState } from "react";
import * as settingsApi from "../api/settings";
import type {
  ParserPostprocessSettings,
  ParserSettings,
  PdfMarkdownSettings,
  QwenCacheMaintenanceResponse,
  QwenEventJournalResponse,
  QwenReadinessResponse,
  QwenSettings,
  QwenTestResult,
  QwenUploadTestResult,
  SettingsSectionKey,
  SystemSettings,
  SystemSettingsSchema,
} from "../types/settings";

const TAB_LABELS: Record<string, string> = {
  parser: "Парсер",
  pdf_markdown: "PDF / Markdown",
  qwen: "Qwen / AI",
  workers: "Очереди и воркеры",
  system: "Система",
};

const SOURCE_HINTS: Record<string, string> = {
  CORE: "Большой академический индекс. Может отдавать много дублей и требовать аккуратный лимит.",
  arXiv: "Быстрый источник препринтов. Обычно хорошо подходит для проверки pipeline.",
  OpenAlex: "Широкий индекс метаданных. Полезен для массового поиска, PDF часто отсутствует.",
  Crossref: "DOI и издательские метаданные. PDF зависит от внешних ссылок.",
  EuropePMC: "Биомедицинские статьи и открытые full-text записи.",
  CyberLeninka: "Русскоязычные статьи. Возможны сетевые ограничения и нестабильная разметка.",
  eLibrary: "Осторожный источник: возможны ограничения, капчи, 403/429.",
  Rospatent: "Российские патенты. Лучше держать умеренный лимит.",
  FreePatent: "Патентный источник. Может быть шумным по нерелевантным результатам.",
  GooglePatents: "Google Patents. Получение карточки по номеру публикации или прямой ссылке.",
  PATENTSCOPE: "WIPO/PATENTSCOPE. Полезен для международных патентов, но может быть медленным.",
};

const POSTPROCESS_META: Record<keyof ParserPostprocessSettings, { label: string; hint: string }> = {
  download_pdf: {
    label: "Скачивать PDF",
    hint: "После сохранения статьи пытается найти и скачать PDF. Если выключить, следующие PDF-этапы сработают только при уже существующем локальном файле.",
  },
  extract_pdf_text: {
    label: "Извлекать сырой текст PDF",
    hint: "Создаёт raw_text по страницам/частям. Нужен для хранения исходника и перегенерации одной части без повторного парсинга всей статьи.",
  },
  qwen_markdown: {
    label: "Оцифровывать в Markdown через Qwen",
    hint: "Берёт raw_text из PDF-частей, отправляет в Qwen и сохраняет markdown_text по частям.",
  },
  qwen_ru_analysis: {
    label: "Делать русский анализ",
    hint: "После Markdown просит Qwen сделать русскоязычное описание/анализ статьи.",
  },
  qwen_keywords: {
    label: "Выделять ключевые слова",
    hint: "Извлекает ключевые слова через Qwen только из текста документа и сохраняет только подтверждённые совпадения. Если выключить, могут остаться внешние keywords источника.",
  },
  embedding: {
    label: "Создавать embedding и индексировать",
    hint: "Индексирует текст в ChromaDB для векторного поиска/RAG. Тяжёлый этап по памяти и CPU.",
  },
};

const READONLY_LABELS: Record<string, string> = {
  celery_queue: "Очередь обычных задач",
  content_queue: "Очередь PDF/контента",
  qwen_queue: "Очередь Qwen",
  redis_broker: "Redis broker",
  redis_result_backend: "Redis results",
  content_workers: "Content worker-процессов",
  qwen_workers: "Qwen worker-процессов",
  content_pool: "Pool content worker-а",
  content_concurrency: "Параллельность content worker-а",
  requires_restart: "Требует перезапуска",
  debug: "Debug mode",
  api_host: "API host",
  api_port: "API port",
  chroma_db_path: "ChromaDB path",
  embedding_model: "Embedding model",
  qwen_service_url: "Qwen service URL",
  secrets_note: "Секреты",
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function toInt(value: unknown, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.floor(parsed) : fallback;
}

function boolLabel(value: boolean) {
  return value ? "Да" : "Нет";
}

function formatReadonly(value: unknown) {
  if (typeof value === "boolean") return boolLabel(value);
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function sectionTitle(key: string) {
  return TAB_LABELS[key] || key;
}

function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label className={`settings-toggle${disabled ? " disabled" : ""}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>
        <strong>{label}</strong>
        {hint && <small>{hint}</small>}
      </span>
    </label>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  hint,
  suffix,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <div className="settings-input-row">
        <input
          className="input"
          type="number"
          min={min}
          max={max}
          step={step}
          value={Number.isFinite(value) ? value : 0}
          onChange={(event) => onChange(toInt(event.target.value, value || 0))}
        />
        {suffix && <em>{suffix}</em>}
      </div>
      {hint && <small>{hint}</small>}
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <input className="input" type="text" value={value || ""} onChange={(event) => onChange(event.target.value)} />
      {hint && <small>{hint}</small>}
    </label>
  );
}

function SaveBar({
  saving,
  saveLabel,
  onSave,
  onReset,
}: {
  saving: boolean;
  saveLabel: string;
  onSave: () => void;
  onReset: () => void;
}) {
  return (
    <div className="settings-actions settings-card-wide">
      <button className="btn btn-primary" disabled={saving} onClick={onSave}>
        {saving ? "Сохранение..." : saveLabel}
      </button>
      <button className="btn" disabled={saving} onClick={onReset}>
        Сбросить раздел
      </button>
    </div>
  );
}

function ParserSettingsPanel({
  settings,
  sources,
  saving,
  onChange,
  onSave,
  onReset,
}: {
  settings: ParserSettings;
  sources: string[];
  saving: boolean;
  onChange: (next: ParserSettings) => void;
  onSave: () => void;
  onReset: () => void;
}) {
  const set = (patch: Partial<ParserSettings>) => onChange({ ...settings, ...patch });
  const setPostprocess = (key: keyof ParserPostprocessSettings, checked: boolean) => {
    set({ postprocess: { ...settings.postprocess, [key]: checked } });
  };

  const effectiveMaxLimit = Math.max(1, settings.max_limit || 1);
  const enabledSourceCount = sources.filter((source) => settings.enabled_sources?.[source] ?? true).length;
  const warnings: string[] = [];

  if (settings.default_limit > settings.max_limit) {
    warnings.push("Лимит по умолчанию больше максимального: backend при сохранении обрежет значение до максимального.");
  }
  if (settings.postprocess?.qwen_markdown && !settings.postprocess?.extract_pdf_text) {
    warnings.push("Qwen Markdown включён, но извлечение raw PDF-текста выключено. Новые статьи без уже сохранённых частей не смогут нормально оцифроваться.");
  }
  if (settings.postprocess?.extract_pdf_text && !settings.postprocess?.download_pdf) {
    warnings.push("Извлечение текста включено без скачивания PDF: сработает только для статей, где PDF уже лежит локально.");
  }
  if (enabledSourceCount === 0) {
    warnings.push("Все источники выключены: новые задачи парсинга будут отклоняться.");
  }

  return (
    <div className="settings-grid">
      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Общие</h3>
          <span className={`settings-pill ${settings.enabled ? "ok" : "warn"}`}>{settings.enabled ? "Включено" : "Выключено"}</span>
        </div>
        <Toggle
          checked={settings.enabled}
          onChange={(enabled) => set({ enabled })}
          label="Парсинг включён"
          hint="Выключение запрещает запуск новых parse-задач. Уже активные Celery-задачи не останавливает."
        />
        <div className="settings-form-grid">
          <NumberField
            label="Лимит по умолчанию"
            min={1}
            max={500}
            value={settings.default_limit}
            onChange={(default_limit) => set({ default_limit })}
            hint="Используется, когда frontend/API не передал limit или передал некорректное значение."
            suffix="статей"
          />
          <NumberField
            label="Максимальный лимит"
            min={1}
            max={5000}
            value={settings.max_limit}
            onChange={(max_limit) => set({ max_limit })}
            hint="Жёсткий верхний предел для одного запуска. Backend обрежет любой больший limit."
            suffix="статей"
          />
          <NumberField
            label="Таймаут parser_alpha"
            min={30}
            max={7200}
            value={settings.subprocess_timeout_seconds}
            onChange={(subprocess_timeout_seconds) => set({ subprocess_timeout_seconds })}
            hint="Максимальное время работы subprocess одного источника/запроса до terminate/kill."
            suffix="сек"
          />
          <NumberField
            label="Retry источника"
            min={0}
            max={10}
            value={settings.retry_count}
            onChange={(retry_count) => set({ retry_count })}
            hint="Сколько повторов разрешить при временной ошибке источника. 0 — без повторов."
            suffix="раз"
          />
          <NumberField
            label="Пауза между retry"
            min={0}
            max={600}
            value={settings.retry_delay_seconds}
            onChange={(retry_delay_seconds) => set({ retry_delay_seconds })}
            hint="Задержка перед повторной попыткой. Для 403/429 лучше не ставить 0."
            suffix="сек"
          />
          <NumberField
            label="Параллельных parse-задач"
            min={1}
            max={20}
            value={settings.max_parallel_parse_jobs}
            onChange={(max_parallel_parse_jobs) => set({ max_parallel_parse_jobs })}
            hint="Логический лимит для parse-задач. Фактическую параллельность всё равно ограничивают worker-ы и очередь celery."
            suffix="задач"
          />
        </div>
        {warnings.length > 0 && (
          <div className="settings-warning-list">
            {warnings.map((warning) => (
              <div key={warning} className="settings-warning">{warning}</div>
            ))}
          </div>
        )}
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Источники</h3>
          <span className="settings-pill">{enabledSourceCount}/{sources.length} включено</span>
        </div>
        <div className="settings-source-table improved">
          <div className="settings-source-head">Источник</div>
          <div className="settings-source-head">Вкл.</div>
          <div className="settings-source-head">Лимит</div>
          <div className="settings-source-head">Комментарий</div>
          {sources.map((source) => {
            const enabled = settings.enabled_sources?.[source] ?? true;
            return (
              <div className={`settings-source-row${enabled ? "" : " disabled-source"}`} key={source}>
                <strong>{source}</strong>
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(event) =>
                    set({
                      enabled_sources: {
                        ...settings.enabled_sources,
                        [source]: event.target.checked,
                      },
                    })
                  }
                />
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={effectiveMaxLimit}
                  value={settings.source_limits?.[source] ?? settings.default_limit}
                  onChange={(event) =>
                    set({
                      source_limits: {
                        ...settings.source_limits,
                        [source]: toInt(event.target.value, settings.default_limit),
                      },
                    })
                  }
                />
                <small>{SOURCE_HINTS[source] || "Обычный источник parser_alpha."}</small>
              </div>
            );
          })}
        </div>
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Pipeline после сохранения</h3>
          <span className="settings-pill">для новых статей</span>
        </div>
        <div className="settings-toggle-grid">
          {(Object.keys(POSTPROCESS_META) as Array<keyof ParserPostprocessSettings>).map((key) => (
            <Toggle
              key={key}
              checked={settings.postprocess?.[key] ?? true}
              onChange={(checked) => setPostprocess(key, checked)}
              label={POSTPROCESS_META[key].label}
              hint={POSTPROCESS_META[key].hint}
            />
          ))}
        </div>
      </section>

      <SaveBar saving={saving} saveLabel="Сохранить парсер" onSave={onSave} onReset={onReset} />
    </div>
  );
}

function PdfMarkdownSettingsPanel({
  settings,
  saving,
  onChange,
  onSave,
  onReset,
}: {
  settings: PdfMarkdownSettings;
  saving: boolean;
  onChange: (next: PdfMarkdownSettings) => void;
  onSave: () => void;
  onReset: () => void;
}) {
  const set = (patch: Partial<PdfMarkdownSettings>) => onChange({ ...settings, ...patch });
  return (
    <div className="settings-grid">
      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Извлечение PDF</h3>
          <span className="settings-pill">качество raw_text</span>
        </div>
        <div className="settings-form-grid">
          <label className="settings-field">
            <span>Основной режим parser</span>
            <select
              className="input"
              value={settings.parser_mode || "auto"}
              onChange={(event) => {
                const parser_mode = event.target.value;
                set({
                  parser_mode,
                  ai_mode: parser_mode === "ai" ? "force" : "off",
                  force_strategy: parser_mode === "ai" ? "ai" : parser_mode === "mypdf" ? "mypdf" : "",
                  extraction_mode: parser_mode === "mypdf" ? "mypdf" : parser_mode === "ai" ? "ai" : "auto",
                  ocr_mode: parser_mode === "mypdf" ? "off" : settings.ocr_mode || "auto",
                  ocr_enabled: parser_mode === "mypdf" ? false : settings.ocr_enabled,
                  extract_tables: parser_mode === "mypdf" ? false : settings.extract_tables,
                  detect_columns: parser_mode === "mypdf" ? false : settings.detect_columns,
                });
              }}
            >
              <option value="auto">auto — обычные алгоритмы + fallback</option>
              <option value="mypdf">mypdf — быстрый текстовый слой без OCR/таблиц</option>
              <option value="ai">ai — принудительный AI-анализ PDF</option>
            </select>
            <small>Это верхнеуровневый режим, который dashboard передаёт как pdf_mode. OCR управляется отдельно.</small>
          </label>
          <label className="settings-field">
            <span>Принудительная стратегия</span>
            <select
              className="input"
              value={settings.force_strategy || ""}
              onChange={(event) => {
                const force_strategy = event.target.value;
                set({
                  force_strategy,
                  extraction_mode: force_strategy || settings.extraction_mode || "auto",
                  parser_mode: force_strategy === "ai" ? "ai" : force_strategy === "mypdf" ? "mypdf" : settings.parser_mode || "auto",
                  ai_mode: force_strategy === "ai" ? "force" : "off",
                  ocr_mode: force_strategy === "ocr" ? "force" : force_strategy === "mypdf" ? "off" : settings.ocr_mode || "auto",
                  ocr_enabled: force_strategy === "ocr" ? true : force_strategy === "mypdf" ? false : settings.ocr_enabled,
                  extract_tables: force_strategy === "mypdf" ? false : settings.extract_tables,
                  detect_columns: force_strategy === "mypdf" ? false : settings.detect_columns,
                });
              }}
            >
              <option value="">не форсировать</option>
              <option value="simple">simple</option>
              <option value="layout">layout</option>
              <option value="columns">columns</option>
              <option value="ocr">ocr</option>
              <option value="mypdf">mypdf</option>
              <option value="ai">ai</option>
            </select>
            <small>Нужно для выборочного режима: руками фиксирует конкретный способ извлечения.</small>
          </label>
          <label className="settings-field">
            <span>OCR режим</span>
            <select
              className="input"
              value={settings.ocr_mode || (settings.ocr_enabled ? "auto" : "off")}
              onChange={(event) => {
                const ocr_mode = event.target.value;
                set({ ocr_mode, ocr_enabled: ocr_mode !== "off", force_strategy: ocr_mode === "force" ? "ocr" : settings.force_strategy });
              }}
            >
              <option value="auto">auto — только когда мало текста</option>
              <option value="force">force — принудительно OCR</option>
              <option value="off">off — не использовать OCR</option>
            </select>
            <small>OCR — отдельный fallback/ручной режим, не то же самое, что AI-анализ.</small>
          </label>
          <label className="settings-field">
            <span>AI режим</span>
            <select
              className="input"
              value={settings.ai_mode || "off"}
              onChange={(event) => {
                const ai_mode = event.target.value;
                set({ ai_mode, parser_mode: ai_mode === "force" ? "ai" : settings.parser_mode || "auto", force_strategy: ai_mode === "force" ? "ai" : settings.force_strategy });
              }}
            >
              <option value="off">off — выключен</option>
              <option value="auto">auto — как fallback</option>
              <option value="force">force — принудительно AI</option>
            </select>
            <small>AI получает текст/страницы как дополнительный способ восстановления содержания, а не основной Markdown-output.</small>
          </label>
          <label className="settings-field">
            <span>Режим извлечения</span>
            <select
              className="input"
              value={settings.extraction_mode || "auto"}
              onChange={(event) => set({ extraction_mode: event.target.value })}
            >
              <option value="auto">auto — выбрать лучший результат</option>
              <option value="layout">layout — сохранить расположение</option>
              <option value="columns">columns — читать две колонки</option>
              <option value="simple">simple — обычный текст</option>
              <option value="ocr">ocr — OCR при наличии зависимостей</option>
              <option value="mypdf">mypdf — быстрый текстовый слой без OCR/таблиц</option>
              <option value="ai">ai — AI-анализ страницы</option>
            </select>
            <small>auto сравнивает layout/simple/columns по quality score. mypdf — самый быстрый режим: только текстовый слой PDF, без OCR, фото и восстановления таблиц.</small>
          </label>
          <NumberField
            label="Мин. символов страницы"
            min={0}
            max={10000}
            value={settings.min_text_chars ?? 300}
            onChange={(min_text_chars) => set({ min_text_chars })}
            hint="Если извлечено меньше — страница помечается как проблемная; при включённом OCR будет попытка распознавания."
            suffix="симв."
          />
          <NumberField
            label="Макс. символов страницы"
            min={5000}
            max={250000}
            value={settings.max_page_chars ?? 60000}
            onChange={(max_page_chars) => set({ max_page_chars })}
            hint="Защита от слишком шумных страниц и гигантских таблиц до отправки в Qwen."
            suffix="симв."
          />
        </div>
        <div className="settings-toggle-grid">
          <Toggle checked={settings.detect_columns} onChange={(detect_columns) => set({ detect_columns })} label="Детект двух колонок" hint="Если страница похожа на двухколоночную, текст читается слева направо по колонкам." />
          <Toggle checked={settings.extract_tables} onChange={(extract_tables) => set({ extract_tables })} label="Извлекать таблицы" hint="Таблицы добавляются в raw_text как Markdown table candidates." />
          <Toggle checked={settings.remove_headers_footers} onChange={(remove_headers_footers) => set({ remove_headers_footers })} label="Убирать колонтитулы" hint="Удаляет повторяющиеся шапки/подвалы и одиночные номера страниц." />
          <Toggle checked={settings.merge_hyphenated_words} onChange={(merge_hyphenated_words) => set({ merge_hyphenated_words })} label="Склеивать переносы" hint="nickel-based super-↵alloys → nickel-based superalloys." />
          <Toggle checked={settings.mark_formula_candidates} onChange={(mark_formula_candidates) => set({ mark_formula_candidates })} label="Помечать формулы" hint="Короткие строки с математическими символами помечаются как [Formula candidate] для Qwen." />
        </div>
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>OCR fallback</h3>
          <span className={`settings-pill ${settings.ocr_mode === "force" ? "warn" : ""}`}>{settings.ocr_mode || (settings.ocr_enabled ? "auto" : "off")}</span>
        </div>
        <div className="settings-toggle-grid">
          <Toggle
            checked={settings.ocr_mode !== "off" && settings.ocr_enabled}
            onChange={(ocr_enabled) => set({ ocr_enabled, ocr_mode: ocr_enabled ? "auto" : "off" })}
            label="Использовать OCR для сканов"
            hint="Работает только если установлены PyMuPDF, Pillow, pytesseract и системный Tesseract. Без зависимостей страница получит warning."
          />
        </div>
        <div className="settings-form-grid">
          <label className="settings-field">
            <span>OCR engine</span>
            <select className="input" value={settings.ocr_engine || "auto"} onChange={(event) => set({ ocr_engine: event.target.value })}>
              <option value="auto">auto</option>
              <option value="tesseract">tesseract</option>
              <option value="paddle">paddle</option>
              <option value="surya">surya</option>
              <option value="ocrmypdf">ocrmypdf</option>
            </select>
            <small>Backend сам пропустит недоступный движок и запишет warning.</small>
          </label>
          <NumberField label="DPI OCR" min={120} max={400} value={settings.ocr_dpi ?? 220} onChange={(ocr_dpi) => set({ ocr_dpi })} hint="Выше DPI — лучше распознавание, но тяжелее CPU/RAM." suffix="dpi" />
          <TextField label="Языки OCR" value={settings.ocr_languages || "eng+rus"} onChange={(ocr_languages) => set({ ocr_languages })} hint="Формат Tesseract: eng, rus или eng+rus." />
        </div>
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>AI PDF fallback</h3>
          <span className={`settings-pill ${settings.ai_mode === "force" ? "warn" : ""}`}>{settings.ai_mode || "off"}</span>
        </div>
        <div className="settings-form-grid">
          <TextField label="AI provider" value={settings.ai_provider || ""} onChange={(ai_provider) => set({ ai_provider })} hint="Например qwen/local. Пусто — использовать backend default." />
          <TextField label="AI model" value={settings.ai_model || ""} onChange={(ai_model) => set({ ai_model })} hint="Пусто — использовать модель из Qwen settings/.env." />
          <TextField label="AI endpoint" value={settings.ai_endpoint || ""} onChange={(ai_endpoint) => set({ ai_endpoint })} hint="Опциональный endpoint сервиса анализа страниц." />
          <NumberField label="AI render DPI" min={120} max={500} value={settings.ai_render_dpi ?? 220} onChange={(ai_render_dpi) => set({ ai_render_dpi })} hint="DPI рендера страницы в изображение для AI fallback." suffix="dpi" />
          <label className="settings-field">
            <span>Формат изображения</span>
            <select className="input" value={settings.ai_page_image_format || "png"} onChange={(event) => set({ ai_page_image_format: event.target.value })}>
              <option value="png">png</option>
              <option value="jpeg">jpeg</option>
              <option value="jpg">jpg</option>
              <option value="webp">webp</option>
            </select>
            <small>PNG обычно безопаснее для текста и формул.</small>
          </label>
          <NumberField label="AI timeout" min={5} max={1800} value={settings.ai_timeout_sec ?? 120} onChange={(ai_timeout_sec) => set({ ai_timeout_sec })} hint="Таймаут одного AI-запроса по странице/части." suffix="сек." />
        </div>
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Разбиение для Qwen</h3>
          <span className="settings-pill">raw → markdown</span>
        </div>
        <div className="settings-form-grid">
          <NumberField
            label="Страниц за Qwen-запрос"
            min={1}
            max={10}
            value={settings.pages_per_request}
            onChange={(pages_per_request) => set({ pages_per_request })}
            hint="1 — меньше риск галлюцинаций и проще перегенерировать часть. 2–5 — быстрее, но тяжелее для Qwen."
            suffix="стр."
          />
          <NumberField
            label="Макс. символов части"
            min={1000}
            max={60000}
            value={settings.page_chars}
            onChange={(page_chars) => set({ page_chars })}
            hint="Обрезает слишком длинный сырой текст части перед отправкой в Qwen. Для научных PDF обычно 12000–18000."
            suffix="симв."
          />
        </div>
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Хранение и нормализация</h3>
          <span className="settings-pill">paper_content_parts</span>
        </div>
        <div className="settings-toggle-grid">
          <Toggle checked={settings.save_raw_parts} onChange={(save_raw_parts) => set({ save_raw_parts })} label="Сохранять raw_text" hint="Хранит исходный текст из PDF по частям. Нужен для сравнения с Markdown и точечной перегенерации." />
          <Toggle checked={settings.save_markdown_parts} onChange={(save_markdown_parts) => set({ save_markdown_parts })} label="Сохранять markdown_text" hint="Хранит результат Qwen по каждой части, а не только общий papers.full_text." />
          <Toggle checked={settings.normalize_math} onChange={(normalize_math) => set({ normalize_math })} label="Нормализовать формулы" hint="Приводит \\( ... \\) и \\[ ... \\] к KaTeX-совместимым $...$ и $$...$$." />
          <Toggle
            checked={settings.show_extraction_diagnostics ?? true}
            onChange={(show_extraction_diagnostics) => set({ show_extraction_diagnostics })}
            label="Показывать диагностику извлечения"
            hint="Если выключить, пользователи увидят только текст без качества, метода и предупреждений по страницам."
          />
        </div>
      </section>

      <SaveBar saving={saving} saveLabel="Сохранить PDF / Markdown" onSave={onSave} onReset={onReset} />
    </div>
  );
}


function qwenStatusLabel(status: any) {
  if (!status) return "не проверялся";
  if (status.status === "service_unavailable" || status.service_available === false) return "сервис недоступен";
  if (status.expired) return "истёк";
  if (status.status === "missing") return "не задан";
  if (status.status === "rate_limited" || status.rate_limited) return "действителен / лимит провайдера";
  if (status.valid) return "действителен";
  if (status.status === "unknown" || status.status === "bad_response") return "неизвестно";
  return "не прошёл проверку";
}

function qwenStatusClass(status: any) {
  if (!status) return "";
  if (status.valid) return "ok";
  if (status.status === "service_unavailable" || status.service_available === false || status.expired || status.status === "invalid") return "danger";
  return "warn";
}

function qwenCheckLabel(status: any) {
  const check = status?.checked_by || status?.source;
  if (check === "smoke_chat") return "реальный тестовый чат";
  if (check === "provider_user_api") return "live-проверка Qwen user API";
  if (status?.cached) return "кэш без live-запроса";
  return "не проверялся";
}

function qwenMaxSessionsLabel(status: any) {
  const max = status?.max_active_sessions;
  if (max === null || max === undefined || max === "") return "— / —";
  return `${status?.active_sessions ?? "—"} / ${max}`;
}

function qwenEffectiveModelLabel(settings: QwenSettings, status: any) {
  const configured = settings.model || "—";
  const effective = status?.model || "—";
  if (!status?.model || status.model === settings.model) return configured;
  return `${configured} / фактически ${effective}`;
}

function qwenReadinessStatusLabel(result: QwenReadinessResponse | null) {
  if (!result) return "локально не проверялась";
  if (result.status === "unavailable") return "qwen_service недоступен";
  if (result.ok || result.status === "ready" || result.status === "ok") return "локально готово";
  if ((result.error_count || 0) > 0 || result.status === "error") return "есть ошибки";
  return "есть предупреждения";
}

function qwenReadinessStatusClass(result: QwenReadinessResponse | null) {
  if (!result) return "";
  if (result.ok || result.status === "ready" || result.status === "ok") return "ok";
  if ((result.error_count || 0) > 0 || result.status === "error" || result.status === "unavailable") return "danger";
  return "warn";
}

function qwenCacheStatusClass(result: QwenCacheMaintenanceResponse | null) {
  if (!result) return "";
  if (result.status === "unavailable" || result.status === "error") return "danger";
  if ((result.total_candidates || 0) > 0 && result.dry_run) return "warn";
  return "ok";
}

const QWEN_READINESS_CHECK_LABELS: Record<string, string> = {
  service_api_key: "Сервисный ключ qwen_service",
  provider_token: "Qwen token",
  browser_session_headers: "Browser/session headers для файлов",
  file_api_templates: "Шаблоны file API",
  har_directory: "Папка HAR",
  upload_limits: "Лимиты загрузки файлов",
  file_metadata_cache: "Кэш загруженных файлов",
  session_registry_cache: "Кэш Qwen-сессий",
  event_journal: "Журнал событий",
  runtime_clients: "Runtime-клиенты qwen_service",
};

const QWEN_EVENT_LABELS: Record<string, string> = {
  service_start: "Запуск qwen_service",
  readiness: "Локальная диагностика",
  cache_maintenance: "Обслуживание локальных кэшей",
  auth_check: "Проверка Qwen token",
  har_import: "Импорт session из HAR",
  token_update: "Ручное обновление token",
  cdp_refresh: "Обновление session через CDP",
  browser_refresh: "Обновление session через браузер",
  config_update: "Обновление runtime-настроек",
  auto_continue_update: "Настройка auto-continue",
  api_key_update: "Смена service API key",
  model_update: "Смена модели",
  session_create: "Создание Qwen-чата",
  create_session: "Создание Qwen-чата",
  session_rename: "Переименование Qwen-чата",
  session_delete: "Удаление Qwen-чата",
  send_message: "Отправка сообщения",
  continue_message: "Продолжение ответа",
  file_upload: "Загрузка файла",
  upload_and_send: "Загрузка файла и отправка сообщения",
  events_read: "Чтение журнала событий",
  events_clear: "Очистка журнала событий",
};

function humanizeQwenKey(value?: string) {
  if (!value) return "—";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function qwenReadinessCheckLabel(name?: string) {
  if (!name) return "Проверка";
  return QWEN_READINESS_CHECK_LABELS[name] || humanizeQwenKey(name);
}

function qwenEventLabel(event?: string) {
  if (!event) return "Событие";
  return QWEN_EVENT_LABELS[event] || humanizeQwenKey(event);
}

function qwenEventStatusClass(status?: string) {
  if (status === "ok") return "ok";
  if (status === "error") return "danger";
  if (status === "warning" || status === "warn") return "warn";
  return "";
}

function qwenEventStatusLabel(status?: string) {
  if (status === "ok") return "успешно";
  if (status === "error") return "ошибка";
  if (status === "warning" || status === "warn") return "предупр.";
  if (status === "started") return "старт";
  return status || "—";
}

function qwenDiagCheckClass(status?: string) {
  if (status === "ok") return "ok";
  if (status === "error") return "danger";
  return "warn";
}

function qwenDiagCheckStatusLabel(status?: string) {
  if (status === "ok") return "готово";
  if (status === "error") return "ошибка";
  if (status === "warning" || status === "warn") return "предупр.";
  return status || "—";
}

function qwenDiagCheckHasProblem(status?: string) {
  return status === "error" || status === "warning" || status === "warn";
}

function qwenUploadTestSucceeded(result: QwenUploadTestResult | null) {
  return Boolean(result && (result.status === "ok" || result.ok));
}

function qwenReadinessCheckSatisfiedByUpload(check: any, uploadResult: QwenUploadTestResult | null) {
  return check?.name === "file_api_templates" && qwenUploadTestSucceeded(uploadResult) && qwenDiagCheckHasProblem(check?.status);
}

function qwenDisplayDiagStatus(check: any, uploadResult: QwenUploadTestResult | null) {
  if (qwenReadinessCheckSatisfiedByUpload(check, uploadResult)) return "ok";
  return check?.status;
}

function qwenDisplayDiagMessage(check: any, uploadResult: QwenUploadTestResult | null) {
  const message = String(check?.message || "");
  if (!qwenReadinessCheckSatisfiedByUpload(check, uploadResult)) return message;
  return `${message} Последний upload-тест прошёл успешно, значит для текущей сессии это не проблема.`;
}

function qwenUniqueRecommendations(result: QwenReadinessResponse | null, uploadResult: QwenUploadTestResult | null = null) {
  const uploadOk = qwenUploadTestSucceeded(uploadResult);
  const alreadyShown = new Set(
    (result?.checks || [])
      .filter((check) => {
        if (uploadOk && check.name === "file_api_templates") return false;
        return qwenDiagCheckHasProblem(check.status) && check.action;
      })
      .map((check) => String(check.action || "").trim())
      .filter(Boolean),
  );
  const seen = new Set<string>();
  return (result?.recommendations || []).filter((item) => {
    const text = String(item || "").trim();
    if (!text) return false;
    if (uploadOk && /file api|upload-and-send|require_file_api|проверить upload|импортируй свежий har/i.test(text)) return false;
    if (alreadyShown.has(text) || seen.has(text)) return false;
    seen.add(text);
    return true;
  });
}


function compactJsonValue(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (typeof value === "number" || typeof value === "string") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function qwenDetailsPreview(value: unknown) {
  const text = compactJsonValue(value);
  if (text.length <= 160) return text;
  return `${text.slice(0, 160)}…`;
}

function qwenErrorMessage(err: any, fallback: string) {
  const payload = err?.response?.data;
  const detail = payload?.detail;
  const candidates = [
    detail?.message,
    detail?.error,
    detail?.detail?.message,
    payload?.message,
    payload?.error,
    payload?.details?.message,
    typeof detail === "string" ? detail : undefined,
    err?.message,
  ];
  const text = candidates.find((item) => typeof item === "string" && item.trim());
  if (text) return text;
  if (detail && typeof detail === "object") {
    const code = detail.code || detail.error_code || detail.status;
    const message = detail.message || detail.reason || detail.error;
    if (message) return code ? `${message} (${code})` : String(message);
  }
  return fallback;
}

function qwenTextTestIsSequentialOnly(result: QwenTestResult | null) {
  if (!result) return false;
  const message = String(result.message || "").toLowerCase();
  return Boolean(
    result.failed_count === 0
      && (result.successful_count || 0) > 0
      && (
        result.processing_mode === "sequential_or_limited"
        || message.includes("последователь")
        || message.includes("последовательно")
        || message.includes("parallel") === false && result.looks_parallel === false
      )
      && !result.provider_limited
      && result.status !== "rate_limited"
      && result.status !== "error"
  );
}

function qwenTextTestDisplayMessage(result: QwenTestResult | null) {
  if (!result) return "реальный запрос не запускался";
  if (qwenTextTestIsSequentialOnly(result)) {
    if ((result.chat_count || 0) <= 1) return "Текстовый Qwen-запрос успешно выполнен.";
    return "Qwen успешно обработал все тестовые запросы. Последовательная обработка включена или ограничена настройками — это нормальный режим, не ошибка.";
  }
  return result.message || qwenTestStatusLabel(result);
}

function qwenTestStatusLabel(result: QwenTestResult | null) {
  if (!result) return "реальный запрос не запускался";
  if (result.status === "ok" || qwenTextTestIsSequentialOnly(result)) return "реальный запрос успешен";
  if (result.status === "busy") return "Qwen занят";
  if (result.status === "rate_limited") return "лимит провайдера";
  if (result.status === "partial") return "частично";
  if (result.status === "warning") return "нужно проверить";
  return "ошибка реального запроса";
}

function qwenTestStatusClass(result: QwenTestResult | null) {
  if (!result) return "";
  if (result.status === "ok" || qwenTextTestIsSequentialOnly(result)) return "ok";
  if (result.status === "busy") return "warn";
  if (result.status === "error") return "danger";
  return "warn";
}

function qwenTestAlertClass(result: QwenTestResult | null) {
  if (!result) return "alert";
  if (result.ok || qwenTextTestIsSequentialOnly(result)) return "alert alert-success";
  if (result.status === "busy" || result.provider_limited || result.status === "rate_limited" || result.status === "partial" || result.status === "warning") return "alert alert-warning";
  return "alert alert-danger";
}

function qwenTestProcessingLabel(result: QwenTestResult | null) {
  if (!result) return "не проверялся";
  if (result.failed_count > 0 || result.status === "error") return "не определён";
  if (result.processing_mode === "single_request" || result.chat_count <= 1) return "один запрос — параллельность не проверялась";
  if (result.looks_parallel || result.processing_mode === "parallel") return "параллельная обработка подтверждена";
  return "последовательно / с ограничением — нормально, если так настроено";
}


function qwenUploadTestStatusLabel(result: QwenUploadTestResult | null, readiness: QwenReadinessResponse | null) {
  if (result?.status === "ok" || result?.ok) return "реальная загрузка успешна";
  if (result?.status === "busy") return "Qwen занят";
  if (result) return "ошибка реальной загрузки";
  if (!readiness) return "не проверялась";
  const fileChecks = (readiness.checks || []).filter((check) => /file|upload|browser_session|har/i.test(check.name || ""));
  if (fileChecks.some((check) => check.status === "error")) return "есть ошибка локальной подготовки";
  if (fileChecks.some((check) => check.status === "warn" || check.status === "warning")) return "есть предупреждения";
  return "локально готова, реальный upload не запускался";
}

function qwenUploadTestStatusClass(result: QwenUploadTestResult | null, readiness: QwenReadinessResponse | null) {
  if (result?.status === "ok" || result?.ok) return "ok";
  if (result?.status === "busy") return "warn";
  if (result) return "danger";
  if (!readiness) return "";
  const fileChecks = (readiness.checks || []).filter((check) => /file|upload|browser_session|har/i.test(check.name || ""));
  if (fileChecks.some((check) => check.status === "error")) return "danger";
  if (fileChecks.some((check) => check.status === "warn" || check.status === "warning")) return "warn";
  return "ok";
}

function qwenServiceSummary(readiness: QwenReadinessResponse | null, tokenStatus: any) {
  if (readiness?.status === "unavailable" || tokenStatus?.status === "service_unavailable" || tokenStatus?.service_available === false) {
    return { label: "qwen_service недоступен", cls: "danger" };
  }
  if (readiness) return { label: qwenReadinessStatusLabel(readiness), cls: qwenReadinessStatusClass(readiness) };
  if (tokenStatus?.service_available) return { label: "qwen_service отвечает", cls: qwenStatusClass(tokenStatus) || "ok" };
  return { label: "не проверялся", cls: "" };
}

function qwenFileUploadSummary(readiness: QwenReadinessResponse | null, uploadResult: QwenUploadTestResult | null) {
  return {
    label: qwenUploadTestStatusLabel(uploadResult, readiness),
    cls: qwenUploadTestStatusClass(uploadResult, readiness),
  };
}
function QwenSettingsPanel({
  settings,
  saving,
  onChange,
  onSave,
  onReset,
}: {
  settings: QwenSettings;
  saving: boolean;
  onChange: (next: QwenSettings) => void;
  onSave: () => void;
  onReset: () => void;
}) {
  const set = (patch: Partial<QwenSettings>) => onChange({ ...settings, ...patch });
  const [tokenStatus, setTokenStatus] = useState<any>(null);
  const [tokenSource, setTokenSource] = useState<any>(null);
  const [tokenBusy, setTokenBusy] = useState(false);
  const [harFile, setHarFile] = useState<File | null>(null);
  const [tokenMessage, setTokenMessage] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [testBusy, setTestBusy] = useState(false);
  const [testResult, setTestResult] = useState<QwenTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [uploadTestBusy, setUploadTestBusy] = useState(false);
  const [uploadTestResult, setUploadTestResult] = useState<QwenUploadTestResult | null>(null);
  const [uploadTestError, setUploadTestError] = useState<string | null>(null);
  const [testChatCount, setTestChatCount] = useState(1);
  const [testMessage, setTestMessage] = useState("Напиши короткий ответ: OK");
  const [diagBusy, setDiagBusy] = useState(false);
  const [readinessResult, setReadinessResult] = useState<QwenReadinessResponse | null>(null);
  const [maintenanceResult, setMaintenanceResult] = useState<QwenCacheMaintenanceResponse | null>(null);
  const [eventJournal, setEventJournal] = useState<QwenEventJournalResponse | null>(null);
  const [diagError, setDiagError] = useState<string | null>(null);

  async function loadTokenStatus() {
    setTokenBusy(true);
    setTokenError(null);
    setTokenMessage(null);
    try {
      const status = await settingsApi.checkQwenToken();
      setTokenStatus(status);
      setTokenMessage(status?.message || "Проверка Qwen токена завершена.");
    } catch (err: any) {
      setTokenError(qwenErrorMessage(err, "Не удалось проверить Qwen token"));
    } finally {
      setTokenBusy(false);
    }
  }

  async function updateTokenFromHar() {
    if (!harFile) {
      setTokenError("Выберите HAR-файл, экспортированный из chat.qwen.ai.");
      return;
    }
    setTokenBusy(true);
    setTokenError(null);
    setTokenMessage(null);
    try {
      const result = await settingsApi.updateQwenTokenFromHar(harFile);
      setTokenStatus(result.qwen_status);
      setTokenSource(result.token_source || null);
      setTokenMessage(result.message || "Qwen token/session обновлены из файлового HAR.");
      setHarFile(null);
    } catch (err: any) {
      setTokenError(qwenErrorMessage(err, "Не удалось обновить Qwen token/session из HAR. Проверь, что HAR содержит /api/v2/files/* запросы."));
    } finally {
      setTokenBusy(false);
    }
  }

  async function runQwenTest() {
    setTestBusy(true);
    setTestError(null);
    try {
      const result = await settingsApi.runQwenServiceTest({
        chat_count: testChatCount,
        message: testMessage.trim() || "Напиши короткий ответ: OK",
      });
      setTestResult(result);
    } catch (err: any) {
      setTestError(qwenErrorMessage(err, "Не удалось отправить тестовый запрос в Qwen"));
    } finally {
      setTestBusy(false);
    }
  }

  async function runQwenUploadSmokeTest() {
    setUploadTestBusy(true);
    setUploadTestError(null);
    try {
      const result = await settingsApi.runQwenUploadTest({
        message: "Прочитай прикреплённый TXT-файл и ответь одной короткой фразой: файл получен.",
      });
      setUploadTestResult(result);
    } catch (err: any) {
      setUploadTestError(qwenErrorMessage(err, "Не удалось выполнить реальную проверку файловой загрузки Qwen"));
    } finally {
      setUploadTestBusy(false);
    }
  }


  async function loadQwenReadiness() {
    setDiagBusy(true);
    setDiagError(null);
    try {
      const result = await settingsApi.getQwenReadiness();
      setReadinessResult(result);
    } catch (err: any) {
      setDiagError(qwenErrorMessage(err, "Не удалось получить локальную диагностику qwen_service"));
    } finally {
      setDiagBusy(false);
    }
  }

  async function runQwenCacheMaintenance(dryRun = true) {
    setDiagBusy(true);
    setDiagError(null);
    try {
      const result = await settingsApi.runQwenRuntimeCacheMaintenance({ dryRun });
      setMaintenanceResult(result);
    } catch (err: any) {
      setDiagError(qwenErrorMessage(err, "Не удалось выполнить обслуживание локальных кэшей qwen_service"));
    } finally {
      setDiagBusy(false);
    }
  }

  async function loadQwenEvents() {
    setDiagBusy(true);
    setDiagError(null);
    try {
      const result = await settingsApi.getQwenEventJournal({ limit: 50 });
      setEventJournal(result);
    } catch (err: any) {
      setDiagError(qwenErrorMessage(err, "Не удалось получить журнал событий qwen_service"));
    } finally {
      setDiagBusy(false);
    }
  }

  async function clearQwenEvents() {
    setDiagBusy(true);
    setDiagError(null);
    try {
      const result = await settingsApi.clearQwenEventJournal();
      setEventJournal(result);
    } catch (err: any) {
      setDiagError(qwenErrorMessage(err, "Не удалось очистить журнал событий qwen_service"));
    } finally {
      setDiagBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    settingsApi
      .getQwenTokenStatus()
      .then((status) => {
        if (active) setTokenStatus(status);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const serviceSummary = qwenServiceSummary(readinessResult, tokenStatus);
  const fileUploadSummary = qwenFileUploadSummary(readinessResult, uploadTestResult);
  const tokenSummaryClass = qwenStatusClass(tokenStatus);
  const tokenSummaryLabel = qwenStatusLabel(tokenStatus);
  const realRequestClass = qwenTestStatusClass(testResult);
  const realRequestLabel = qwenTestStatusLabel(testResult);
  const qwenManualCheckBusy = testBusy || uploadTestBusy;
  const hasTokenConfigured = Boolean(settings.token_configured || tokenStatus?.token_configured);

  return (
    <div className="settings-grid">
      <section className="panel settings-card settings-card-wide qwen-overview-card">
        <div className="settings-card-title">
          <div>
            <h3>Сводка готовности Qwen</h3>
            <small>Сначала проверь локальный сервис, затем token, потом реальный запрос и файловую загрузку.</small>
          </div>
          <span className={`settings-pill ${serviceSummary.cls}`}>{serviceSummary.label}</span>
        </div>
        <div className="qwen-overview-grid">
          <div className="qwen-overview-item">
            <span>qwen_service</span>
            <strong className={`settings-pill ${serviceSummary.cls}`}>{serviceSummary.label}</strong>
            <small>Локальная проверка без внешнего Qwen: конфиг, service key, HAR, file headers и runtime-кэши.</small>
            <button className="btn btn-sm" disabled={diagBusy} onClick={loadQwenReadiness}>
              {diagBusy ? "Проверка..." : "Проверить локально"}
            </button>
          </div>
          <div className="qwen-overview-item">
            <span>Qwen token</span>
            <strong className={`settings-pill ${tokenSummaryClass}`}>{tokenSummaryLabel}</strong>
            <small>Live-проверка действующего token через qwen_service. Сам token в браузер не выводится.</small>
            <button className="btn btn-sm btn-primary" disabled={tokenBusy} onClick={loadTokenStatus}>
              {tokenBusy ? "Проверка..." : "Проверить token"}
            </button>
          </div>
          <div className="qwen-overview-item">
            <span>Реальный текстовый запрос</span>
            <strong className={`settings-pill ${realRequestClass}`}>{realRequestLabel}</strong>
            <small>Отправляет один короткий запрос во внешний Qwen. Это уже реальный вызов провайдера.</small>
            <button className="btn btn-sm" disabled={qwenManualCheckBusy} onClick={runQwenTest}>
              {testBusy ? "Отправка..." : uploadTestBusy ? "Qwen занят..." : "Отправить текст"}
            </button>
          </div>
          <div className="qwen-overview-item">
            <span>Файловая загрузка</span>
            <strong className={`settings-pill ${fileUploadSummary.cls}`}>{fileUploadSummary.label}</strong>
            <small>Создаёт временный TXT, загружает его в Qwen и отправляет сообщение с файлом.</small>
            <button className="btn btn-sm" disabled={qwenManualCheckBusy} onClick={runQwenUploadSmokeTest}>
              {uploadTestBusy ? "Проверка..." : testBusy ? "Qwen занят..." : "Проверить upload"}
            </button>
          </div>
        </div>
        {(testError || uploadTestError) && (
          <div className="settings-warning-list qwen-overview-errors">
            {testError && <div className="settings-warning settings-warning-danger">Текстовый тест: {testError}</div>}
            {uploadTestError && <div className="settings-warning settings-warning-danger">Upload-тест: {uploadTestError}</div>}
          </div>
        )}
        {(testResult || uploadTestResult) && (
          <div className="settings-kv-grid qwen-overview-results">
            {testResult && (
              <div className="settings-kv-row">
                <span>Последний текстовый тест</span>
                <strong>{qwenTextTestDisplayMessage(testResult)}</strong>
              </div>
            )}
            {uploadTestResult && (
              <div className="settings-kv-row">
                <span>Последний upload-тест</span>
                <strong>{uploadTestResult.message || qwenUploadTestStatusLabel(uploadTestResult, readinessResult)}</strong>
              </div>
            )}
          </div>
        )}
        <div className="settings-muted-box qwen-flow-box">
          Рекомендуемый порядок теперь можно выполнить прямо здесь: <b>Проверить локально</b> → <b>Проверить token</b> → <b>Отправить текст</b> → <b>Проверить upload</b>. Upload-тест вызывает внешний Qwen и создаёт временный TXT-файл только на время проверки.
        </div>
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Qwen token и session</h3>
          <span className={`settings-pill ${qwenStatusClass(tokenStatus)}`}>
            {qwenStatusLabel(tokenStatus)}
          </span>
        </div>

        <div className={`qwen-token-status-card qwen-token-status-card-${qwenStatusClass(tokenStatus) || "neutral"}`}>
          <div>
            <strong>{tokenStatus?.message || "Проверка действующего токена ещё не выполнялась."}</strong>
            <small>
              Проверяет текущий token, уже загруженный в qwen_service из .env или последнего HAR. Сам token не показывается, не попадает в браузер и не хранится во frontend.
            </small>
          </div>
          <div className="qwen-token-actions">
            <button className="btn btn-primary" disabled={tokenBusy} onClick={loadTokenStatus}>
              {tokenBusy ? "Проверка..." : "Проверить действующий token"}
            </button>
          </div>
        </div>

        <div className="settings-kv-grid qwen-token-metrics">
          <div className="settings-kv-row">
            <span>Token работает</span>
            <strong>{tokenStatus?.valid ? "да" : tokenStatus?.expired ? "истёк" : "не подтверждён"}</strong>
          </div>
          <div className="settings-kv-row">
            <span>Token задан</span>
            <strong>{tokenStatus?.token_configured || settings.token_configured ? "да" : "нет"}</strong>
          </div>
          <div className="settings-kv-row">
            <span>Проверка</span>
            <strong>{qwenCheckLabel(tokenStatus)}</strong>
          </div>
          <div className="settings-kv-row">
            <span>Модель</span>
            <strong>{qwenEffectiveModelLabel(settings, tokenStatus)}</strong>
          </div>
          <div className="settings-kv-row">
            <span>Активных чатов</span>
            <strong>{qwenMaxSessionsLabel(tokenStatus)}</strong>
          </div>
          <div className="settings-kv-row">
            <span>Лимит запросов провайдера</span>
            <strong>{tokenStatus?.provider_max_concurrent_requests ?? "—"}</strong>
          </div>
        </div>

        <div className="qwen-har-guide">
          <strong>Обновление Qwen session из HAR</strong>
          <small className="qwen-danger-text">HAR содержит cookies, bx-session и token. Загружай только свой HAR и удали файл после обновления.</small>
          <details>
            <summary>Что такое HAR и как его получить?</summary>
            <ol>
              <li>Открой <b>chat.qwen.ai</b> в обычном браузере и войди в аккаунт Qwen.</li>
              <li>Открой инструменты разработчика: F12 или Ctrl+Shift+I.</li>
              <li>Перейди во вкладку <b>Network / Сеть</b>, включи <b>Preserve log</b> и очисти список запросов.</li>
              <li>Загрузи на сайте Qwen небольшой файл и дождись, пока он обработается.</li>
              <li>Убедись, что в Network есть запросы <b>/api/v2/files/getstsToken</b>, <b>/api/v2/files/parse</b> и <b>/api/v2/files/parse/status</b>.</li>
              <li>Нажми правой кнопкой по списку запросов и выбери <b>Save all as HAR with content</b>.</li>
              <li>Загрузи полученный .har файл ниже и нажми <b>Обновить token/session из HAR</b>.</li>
            </ol>
          </details>
        </div>
        <div className="qwen-har-update-row">
          <input
            className="input"
            type="file"
            accept=".har,application/json"
            onChange={(event) => setHarFile(event.target.files?.[0] || null)}
          />
          <button className="btn" disabled={tokenBusy || !harFile} onClick={updateTokenFromHar}>
            {tokenBusy ? "Обновление..." : "Обновить token/session из HAR"}
          </button>
        </div>
        {tokenSource && (
          <div className="settings-muted-box">
            Источник HAR: {tokenSource.source || "—"}; файловых кандидатов: {tokenSource.file_session_candidates_count || tokenSource.selected_session_candidates_count || 0}; token: {tokenSource.token_preview || "***"}
          </div>
        )}
        {tokenMessage && <div className={`alert ${tokenStatus?.valid ? "alert-success" : "alert-info"}`}>{tokenMessage}<br /><small>Следующий шаг: проверь token и затем отправь тестовый запрос. Для файлового pipeline запусти upload-and-send probe.</small></div>}
        {tokenError && <div className="alert alert-danger">{tokenError}</div>}
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Этапы Qwen</h3>
          <span className={`settings-pill ${hasTokenConfigured ? "ok" : "warn"}`}>
            token {hasTokenConfigured ? "задан" : "не задан"}
          </span>
        </div>
        <div className="settings-toggle-grid">
          <Toggle
            checked={settings.markdown_enabled}
            onChange={(markdown_enabled) => set({ markdown_enabled })}
            label="Markdown-оцифровка"
            hint="Если выключить, Qwen не будет преобразовывать raw PDF-текст в Markdown. Остальные этапы будут работать с доступным текстом."
          />
          <Toggle
            checked={settings.ru_analysis_enabled}
            onChange={(ru_analysis_enabled) => set({ ru_analysis_enabled })}
            label="Русский анализ"
            hint="Краткий русскоязычный разбор статьи после Markdown."
          />
          <Toggle
            checked={settings.keywords_enabled}
            onChange={(keywords_enabled) => set({ keywords_enabled })}
            label="Ключевые слова"
            hint="Извлечение keywords только из текста документа: Qwen получает TXT, а backend сохраняет только слова/фразы, найденные в исходнике."
          />
        </div>
        {!hasTokenConfigured && (
          <div className="settings-warning-list">
            <div className="settings-warning">QWEN_TOKEN не задан: Qwen-этапы будут недоступны.</div>
          </div>
        )}
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Запросы</h3>
          <span className="settings-pill">без секретов</span>
        </div>
        <div className="settings-form-grid">
          <TextField
            label="Модель"
            value={settings.model}
            onChange={(model) => set({ model })}
            hint="Имя модели, которое backend передаёт в qwen_service. Фактическое значение видно в сводке token/status выше."
          />
          <NumberField
            label="Timeout Qwen-запроса"
            min={30}
            max={1800}
            value={settings.request_timeout_seconds}
            onChange={(request_timeout_seconds) => set({ request_timeout_seconds })}
            hint="Сколько ждать один запрос к Qwen gateway/service. Для длинных PDF лучше 300–900 сек."
            suffix="сек"
          />
        </div>
      </section>

      <SaveBar saving={saving} saveLabel="Сохранить настройки Qwen / AI" onSave={onSave} onReset={onReset} />

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Диагностика и локальные кэши qwen_service</h3>
          <span className={`settings-pill ${qwenReadinessStatusClass(readinessResult)}`}>
            {qwenReadinessStatusLabel(readinessResult)}
          </span>
        </div>
        <div className="qwen-token-status-card">
          <div>
            <strong>Локальная диагностика не отправляет запросы во внешний Qwen. Она проверяет конфиг, HAR, file API templates, служебные кэши и runtime-состояние.</strong>
            <small>Используй её перед настоящим text/upload тестом, чтобы быстро увидеть: не готов service API key, token, HAR, file headers или локальные кэши.</small>
          </div>
          <div className="qwen-token-actions">
            <button className="btn" disabled={diagBusy} onClick={loadQwenReadiness}>
              {diagBusy ? "Проверка..." : "Проверить локальную готовность"}
            </button>
            <button className="btn" disabled={diagBusy} onClick={() => runQwenCacheMaintenance(true)}>
              Проверить, что можно очистить
            </button>
            <button
              className="btn btn-danger"
              disabled={diagBusy}
              onClick={() => {
                if (window.confirm("Удалить устаревшие локальные записи qwen_service? Чаты и файлы на стороне Qwen не удаляются. Внешний Qwen вызван не будет.")) {
                  runQwenCacheMaintenance(false);
                }
              }}
            >
              Очистить устаревшие локальные записи
            </button>
          </div>
        </div>
        {diagError && <div className="alert alert-danger">{diagError}</div>}
        {readinessResult && (
          <>
            <div className="settings-kv-grid">
              <div className="settings-kv-row">
                <span>Адрес qwen_service</span>
                <strong>{readinessResult.base_url || "—"}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Проверок</span>
                <strong>{readinessResult.check_count ?? readinessResult.checks?.length ?? 0}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Ошибок</span>
                <strong>{readinessResult.error_count ?? 0}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Предупреждений</span>
                <strong>{readinessResult.warning_count ?? 0}</strong>
              </div>
            </div>
            <div className="settings-warning-list">
              {(readinessResult.checks || []).map((check) => {
                const displayStatus = qwenDisplayDiagStatus(check, uploadTestResult);
                const solvedByUpload = qwenReadinessCheckSatisfiedByUpload(check, uploadTestResult);
                return (
                  <div key={check.name} className="settings-warning qwen-diagnostic-row">
                    <span className={`settings-pill ${qwenDiagCheckClass(displayStatus)}`}>{qwenDiagCheckStatusLabel(displayStatus)}</span>{" "}
                    <b>{qwenReadinessCheckLabel(check.name)}</b>: {qwenDisplayDiagMessage(check, uploadTestResult)}
                    {solvedByUpload ? <small> Проверка upload уже подтвердила работоспособность файлового pipeline.</small> : null}
                    {!solvedByUpload && qwenDiagCheckHasProblem(check.status) && check.action ? <small> Что сделать: {check.action}</small> : null}
                  </div>
                );
              })}
              {qwenUniqueRecommendations(readinessResult, uploadTestResult).map((item, index) => (
                <div key={`recommendation-${index}`} className="settings-warning settings-warning-action">Рекомендация: {item}</div>
              ))}
            </div>
          </>
        )}
        {maintenanceResult && (
          <>
            <div className={`alert ${qwenCacheStatusClass(maintenanceResult) === "danger" ? "alert-danger" : qwenCacheStatusClass(maintenanceResult) === "warn" ? "alert-warning" : "alert-success"}`}>
              {maintenanceResult.message || (maintenanceResult.dry_run ? "Проверка локальных кэшей завершена." : "Устаревшие локальные записи очищены.")}
            </div>
            <div className="settings-kv-grid">
              <div className="settings-kv-row">
                <span>Режим</span>
                <strong>{maintenanceResult.dry_run ? "только проверка" : "очистка"}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Внешний Qwen</span>
                <strong>{maintenanceResult.provider_called ? "вызывался" : "не вызывался"}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Кандидатов</span>
                <strong>{maintenanceResult.total_candidates ?? 0}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Удалено</span>
                <strong>{maintenanceResult.total_removed ?? 0}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Кэш загруженных файлов</span>
                <strong>{compactJsonValue(maintenanceResult.operations?.file_metadata || maintenanceResult.file_metadata)}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Кэш Qwen-сессий</span>
                <strong>{compactJsonValue(maintenanceResult.operations?.session_registry || maintenanceResult.session_registry)}</strong>
              </div>
            </div>
          </>
        )}

        <div className="qwen-token-status-card">
          <div>
            <strong>Журнал последних операций qwen_service</strong>
            <small>Локальные записи без секретов: диагностика, auth-check, HAR import, отправка сообщений, upload и обслуживание кэшей. Внешний Qwen при чтении журнала не вызывается.</small>
          </div>
          <div className="qwen-token-actions">
            <button className="btn" disabled={diagBusy} onClick={loadQwenEvents}>Обновить журнал</button>
            <button
              className="btn btn-danger"
              disabled={diagBusy}
              onClick={() => {
                if (window.confirm("Очистить локальный журнал событий qwen_service? Это не удаляет чаты и файлы у Qwen.")) {
                  clearQwenEvents();
                }
              }}
            >
              Очистить журнал
            </button>
          </div>
        </div>
        {eventJournal?.message && (
          <div className={`alert ${eventJournal.status === "error" || eventJournal.status === "unavailable" ? "alert-danger" : "alert-success"}`}>
            {eventJournal.message}
          </div>
        )}
        {eventJournal && (
          <div className="settings-warning-list">
            {(eventJournal.events || []).length === 0 ? (
              <div className="settings-warning">Журнал пуст или qwen_service пока не вернул событий.</div>
            ) : (
              (eventJournal.events || []).map((item, index) => (
                <div key={`${item.ts}-${item.event}-${index}`} className="settings-warning qwen-event-row">
                  <div className="qwen-event-main">
                    <span className={`settings-pill ${qwenEventStatusClass(item.status)}`}>{qwenEventStatusLabel(item.status)}</span>{" "}
                    <b>{qwenEventLabel(item.event)}</b>
                    <small>{item.ts}</small>
                    {item.session_tail ? <small>session: …{item.session_tail}</small> : null}
                  </div>
                  {item.message ? <div>{item.message}</div> : null}
                  {item.details ? (
                    <details className="qwen-event-details">
                      <summary>Детали события</summary>
                      <code>{qwenDetailsPreview(item.details)}</code>
                    </details>
                  ) : null}
                </div>
              ))
            )}
          </div>
        )}
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Реальный тест Qwen</h3>
          <span className={`settings-pill ${qwenTestStatusClass(testResult)}`}>{qwenTestStatusLabel(testResult)}</span>
        </div>
        <div className="settings-form-grid">
          <NumberField
            label="Тестовых чатов"
            min={1}
            max={50}
            value={testChatCount}
            onChange={setTestChatCount}
            hint="1 чат — быстрая проверка. 3–5 чатов — расширенный тест. Большие значения создают нагрузку и могут упереться в лимит провайдера."
            suffix="чатов"
          />
          <label className="settings-field settings-card-wide">
            <span>Стартовое сообщение</span>
            <textarea
              className="input"
              rows={4}
              value={testMessage}
              onChange={(event) => setTestMessage(event.target.value)}
              placeholder="Введите сообщение для реальной отправки во внешний Qwen."
            />
            <small>Это сообщение реально уйдёт во внешний Qwen. Для быстрой проверки оставь 1 чат.</small>
          </label>
        </div>
        <div className="qwen-token-status-card">
          <div>
            <strong>Отправляет реальный тестовый запрос во внешний Qwen.</strong>
            <small>
              Начинай с 1 чата. Расширенный тест на 3–5 чатов используй только если нужно проверить устойчивость; это может создать новые Qwen-чаты и словить rate limit.
            </small>
          </div>
          <div className="qwen-token-actions">
            <button className="btn" disabled={qwenManualCheckBusy} onClick={runQwenTest}>
              {testBusy ? "Отправка..." : uploadTestBusy ? "Qwen занят..." : "Отправить тестовый запрос"}
            </button>
          </div>
        </div>
        {testError && <div className="alert alert-danger">{testError}</div>}
        {testResult && (
          <>
            <div className={qwenTestAlertClass(testResult)}>{qwenTextTestDisplayMessage(testResult)}</div>
            <div className="settings-kv-grid">
              <div className="settings-kv-row">
                <span>Отправленное сообщение</span>
                <strong>{testResult.message_used || "—"}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Адрес сервиса</span>
                <strong>{testResult.service_url}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Успешных чатов</span>
                <strong>{testResult.successful_count} / {testResult.chat_count}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Ошибок</span>
                <strong>{testResult.failed_count}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Лимит провайдера</span>
                <strong>{testResult.rate_limited_count ?? 0}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Режим обработки</span>
                <strong>{qwenTestProcessingLabel(testResult)}</strong>
              </div>
              <div className="settings-kv-row">
                <span>Разброс старта</span>
                <strong>{testResult.start_spread_sec ?? "—"} сек</strong>
              </div>
              <div className="settings-kv-row">
                <span>Разброс завершения</span>
                <strong>{testResult.finished_spread_sec ?? "—"} сек</strong>
              </div>
              <div className="settings-kv-row">
                <span>Разброс длительности</span>
                <strong>{testResult.duration_spread_sec ?? "—"} сек</strong>
              </div>
            </div>
            <div className="settings-warning-list">
              {testResult.results.map((item) => (
                <div key={item.chat} className="settings-warning">
                  Чат #{item.chat}: {item.duration_sec} сек; ошибка: {item.error || "нет"}; ответ: {item.response_start || "пусто"}
                </div>
              ))}
            </div>
          </>
        )}
      </section>

    </div>
  );
}

function JsonReadOnlyPanel({ title, value }: { title: string; value: Record<string, any> }) {
  return (
    <section className="panel settings-card settings-card-wide">
      <h3>{title}</h3>
      <div className="settings-kv-grid">
        {Object.entries(value || {}).map(([key, item]) => (
          <div key={key} className="settings-kv-row">
            <span>{READONLY_LABELS[key] || key}</span>
            <strong>{formatReadonly(item)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function TechnicalSettings() {
  const [, setSettings] = useState<SystemSettings | null>(null);
  const [schema, setSchema] = useState<SystemSettingsSchema | null>(null);
  const [activeTab, setActiveTab] = useState<SettingsSectionKey | string>("parser");
  const [draftParser, setDraftParser] = useState<ParserSettings | null>(null);
  const [draftPdfMarkdown, setDraftPdfMarkdown] = useState<PdfMarkdownSettings | null>(null);
  const [draftQwen, setDraftQwen] = useState<QwenSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function hydrateDrafts(next: SystemSettings) {
    setDraftParser(clone(next.parser));
    setDraftPdfMarkdown(clone(next.pdf_markdown));
    setDraftQwen(clone(next.qwen));
  }

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await settingsApi.getSystemSettings();
      setSettings(data.settings);
      setSchema(data.schema);
      hydrateDrafts(data.settings);
    } catch (err: any) {
      setError(err?.message || "Не удалось загрузить настройки");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const sources = useMemo(() => schema?.available_sources || [], [schema]);

  async function saveSection<T extends Record<string, any>>(section: SettingsSectionKey, value: T, successMessage: string) {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = await settingsApi.updateSystemSettingsSection(section, value);
      const nextValue = result.value as T;
      setSettings((prev) => (prev ? { ...prev, [section]: nextValue } : prev));
      if (section === "parser") setDraftParser(nextValue as unknown as ParserSettings);
      if (section === "pdf_markdown") setDraftPdfMarkdown(nextValue as unknown as PdfMarkdownSettings);
      if (section === "qwen") setDraftQwen(nextValue as unknown as QwenSettings);
      setMessage(successMessage);
    } catch (err: any) {
      setError(err?.message || "Не удалось сохранить настройки");
    } finally {
      setSaving(false);
    }
  }

  async function resetSection(section: SettingsSectionKey, successMessage: string) {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = await settingsApi.resetSystemSettingsSection(section);
      const nextValue = result.value;
      setSettings((prev) => (prev ? { ...prev, [section]: nextValue } : prev));
      if (section === "parser") setDraftParser(nextValue as unknown as ParserSettings);
      if (section === "pdf_markdown") setDraftPdfMarkdown(nextValue as unknown as PdfMarkdownSettings);
      if (section === "qwen") setDraftQwen(nextValue as unknown as QwenSettings);
      setMessage(successMessage);
    } catch (err: any) {
      setError(err?.message || "Не удалось сбросить настройки");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page technical-settings-page">
      <div className="page-head settings-page-head">
        <h2>Технический отдел — настройки</h2>
        <button className="btn" onClick={load} disabled={loading || saving}>Обновить</button>
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <div className="tabs settings-tabs">
        {(schema?.sections || []).map((section) => (
          <button
            key={section.key}
            className={`btn ${activeTab === section.key ? "btn-primary" : ""}`}
            onClick={() => setActiveTab(section.key)}
          >
            {section.title || sectionTitle(section.key)}
          </button>
        ))}
      </div>

      {loading && <div className="panel">Загрузка настроек...</div>}

      {!loading && activeTab === "parser" && draftParser && (
        <ParserSettingsPanel
          settings={draftParser}
          sources={sources}
          saving={saving}
          onChange={setDraftParser}
          onSave={() => saveSection("parser", draftParser, "Настройки парсера сохранены.")}
          onReset={() => resetSection("parser", "Настройки парсера сброшены.")}
        />
      )}

      {!loading && activeTab === "pdf_markdown" && draftPdfMarkdown && (
        <PdfMarkdownSettingsPanel
          settings={draftPdfMarkdown}
          saving={saving}
          onChange={setDraftPdfMarkdown}
          onSave={() => saveSection("pdf_markdown", draftPdfMarkdown, "Настройки PDF / Markdown сохранены.")}
          onReset={() => resetSection("pdf_markdown", "Настройки PDF / Markdown сброшены.")}
        />
      )}

      {!loading && activeTab === "qwen" && draftQwen && (
        <QwenSettingsPanel
          settings={draftQwen}
          saving={saving}
          onChange={setDraftQwen}
          onSave={() => saveSection("qwen", draftQwen, "Настройки Qwen / AI сохранены.")}
          onReset={() => resetSection("qwen", "Настройки Qwen / AI сброшены.")}
        />
      )}

      {!loading && activeTab === "workers" && schema?.readonly?.workers && (
        <JsonReadOnlyPanel title="Очереди и воркеры" value={schema.readonly.workers} />
      )}
      {!loading && activeTab === "system" && schema?.readonly?.system && (
        <JsonReadOnlyPanel title="Система" value={schema.readonly.system} />
      )}
    </div>
  );
}
