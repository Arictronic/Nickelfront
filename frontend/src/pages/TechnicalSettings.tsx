import { useEffect, useMemo, useState } from "react";
import * as settingsApi from "../api/settings";
import type {
  ParserPostprocessSettings,
  ParserSettings,
  PdfMarkdownSettings,
  QwenSettings,
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
    hint: "Просит Qwen нормализовать/дополнить ключевые слова. Если выключить, останутся только ключевые слова источника.",
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
            </select>
            <small>auto сравнивает layout/simple/columns по quality score. Для IEEE/arXiv часто помогает columns.</small>
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
          <span className={`settings-pill ${settings.ocr_enabled ? "warn" : ""}`}>{settings.ocr_enabled ? "включён" : "выключен"}</span>
        </div>
        <div className="settings-toggle-grid">
          <Toggle
            checked={settings.ocr_enabled}
            onChange={(ocr_enabled) => set({ ocr_enabled })}
            label="Использовать OCR для сканов"
            hint="Работает только если установлены PyMuPDF, Pillow, pytesseract и системный Tesseract. Без зависимостей страница получит warning."
          />
        </div>
        <div className="settings-form-grid">
          <NumberField label="DPI OCR" min={120} max={400} value={settings.ocr_dpi ?? 220} onChange={(ocr_dpi) => set({ ocr_dpi })} hint="Выше DPI — лучше распознавание, но тяжелее CPU/RAM." suffix="dpi" />
          <TextField label="Языки OCR" value={settings.ocr_languages || "eng+rus"} onChange={(ocr_languages) => set({ ocr_languages })} hint="Формат Tesseract: eng, rus или eng+rus." />
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
  if (status.valid) return "действителен";
  if (status.expired) return "истёк";
  if (status.status === "missing") return "не задан";
  if (status.status === "service_unavailable") return "сервис недоступен";
  return "не прошёл проверку";
}

function qwenStatusClass(status: any) {
  if (!status) return "";
  if (status.valid) return "ok";
  return "warn";
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

  async function loadTokenStatus() {
    setTokenBusy(true);
    setTokenError(null);
    setTokenMessage(null);
    try {
      const status = await settingsApi.checkQwenToken();
      setTokenStatus(status);
      setTokenMessage(status?.message || "Проверка Qwen токена завершена.");
    } catch (err: any) {
      setTokenError(err?.message || "Не удалось проверить Qwen токен");
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
      setTokenMessage(result.message || "Qwen токен обновлён из HAR.");
      setHarFile(null);
    } catch (err: any) {
      setTokenError(err?.message || "Не удалось обновить Qwen токен из HAR");
    } finally {
      setTokenBusy(false);
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

  return (
    <div className="settings-grid">
      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Состояние токена</h3>
          <span className={`settings-pill ${qwenStatusClass(tokenStatus)}`}>
            {qwenStatusLabel(tokenStatus)}
          </span>
        </div>
        <div className="qwen-token-status-card">
          <div>
            <strong>{tokenStatus?.message || "Проверка токена ещё не выполнялась."}</strong>
            <small>
              Токен не показывается и не сохраняется в браузере. HAR читается qwen_service в памяти, из него берётся последний token chat.qwen.ai.
            </small>
          </div>
          <div className="qwen-token-actions">
            <button className="btn" disabled={tokenBusy} onClick={loadTokenStatus}>
              {tokenBusy ? "Проверка..." : "Проверить токен"}
            </button>
          </div>
        </div>
        <div className="qwen-har-guide">
          <strong>Как получить HAR для обновления токена:</strong>
          <ol>
            <li>Открой chat.qwen.ai и выйди из аккаунта Qwen.</li>
            <li>Открой инструменты разработчика: F12 или Ctrl+Shift+I.</li>
            <li>Перейди во вкладку <b>Network / Сеть</b> и включи <b>Preserve log / Сохранять журнал</b>.</li>
            <li>Не закрывая Network, снова войди в аккаунт Qwen.</li>
            <li>После входа нажми правой кнопкой по списку запросов и выбери <b>Save all as HAR with content</b>.</li>
            <li>Загрузи полученный .har файл ниже и нажми <b>Обновить из HAR</b>.</li>
          </ol>
          <small>HAR содержит cookies и токены авторизации. Не отправляй его посторонним; после обновления токена файл лучше удалить.</small>
        </div>
        <div className="qwen-har-update-row">
          <input
            className="input"
            type="file"
            accept=".har,application/json"
            onChange={(event) => setHarFile(event.target.files?.[0] || null)}
          />
          <button className="btn btn-primary" disabled={tokenBusy || !harFile} onClick={updateTokenFromHar}>
            {tokenBusy ? "Обновление..." : "Обновить из HAR"}
          </button>
        </div>
        {tokenSource && (
          <div className="settings-muted-box">
            Источник: {tokenSource.source || "—"}; кандидатов: {tokenSource.candidates_count || 0}; токен: {tokenSource.token_preview || "***"}
          </div>
        )}
        {tokenMessage && <div className="alert alert-success">{tokenMessage}</div>}
        {tokenError && <div className="alert alert-danger">{tokenError}</div>}
      </section>

      <section className="panel settings-card settings-card-wide">
        <div className="settings-card-title">
          <h3>Этапы Qwen</h3>
          <span className={`settings-pill ${settings.token_configured || tokenStatus?.token_configured ? "ok" : "warn"}`}>
            токен {settings.token_configured || tokenStatus?.token_configured ? "задан" : "не задан"}
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
            hint="Нормализация и дополнение keywords через Qwen."
          />
        </div>
        {!settings.token_configured && !tokenStatus?.token_configured && (
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
            hint="Имя модели, которое backend передаёт в qwen_service. Если сервис игнорирует model, значение останется справочным."
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

      <SaveBar saving={saving} saveLabel="Сохранить Qwen / AI" onSave={onSave} onReset={onReset} />
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
  const [settings, setSettings] = useState<SystemSettings | null>(null);
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
      if (section === "parser") setDraftParser(nextValue as ParserSettings);
      if (section === "pdf_markdown") setDraftPdfMarkdown(nextValue as PdfMarkdownSettings);
      if (section === "qwen") setDraftQwen(nextValue as QwenSettings);
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
      if (section === "parser") setDraftParser(nextValue as ParserSettings);
      if (section === "pdf_markdown") setDraftPdfMarkdown(nextValue as PdfMarkdownSettings);
      if (section === "qwen") setDraftQwen(nextValue as QwenSettings);
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
