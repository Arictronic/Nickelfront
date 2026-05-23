import { useEffect, useMemo, useState } from "react";
import * as settingsApi from "../api/settings";
import type { ParserSettings, SettingsSectionKey, SystemSettings, SystemSettingsSchema } from "../types/settings";

const TAB_LABELS: Record<string, string> = {
  parser: "Парсер",
  pdf_markdown: "PDF / Markdown",
  qwen: "Qwen / AI",
  workers: "Очереди и воркеры",
  system: "Система",
};

const POSTPROCESS_LABELS: Record<keyof ParserSettings["postprocess"], string> = {
  download_pdf: "Скачивать PDF",
  extract_pdf_text: "Извлекать сырой текст PDF",
  qwen_markdown: "Оцифровывать в Markdown через Qwen",
  qwen_ru_analysis: "Делать русский анализ",
  qwen_keywords: "Выделять ключевые слова",
  embedding: "Создавать embedding и индексировать",
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function toInt(value: unknown, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.floor(parsed) : fallback;
}

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (next: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="settings-toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>
        <strong>{label}</strong>
        {hint && <small>{hint}</small>}
      </span>
    </label>
  );
}

function NumberField({ label, value, min, max, onChange, hint }: { label: string; value: number; min?: number; max?: number; hint?: string; onChange: (value: number) => void }) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <input
        className="input"
        type="number"
        min={min}
        max={max}
        value={Number.isFinite(value) ? value : 0}
        onChange={(event) => onChange(toInt(event.target.value, value || 0))}
      />
      {hint && <small>{hint}</small>}
    </label>
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
  const setPostprocess = (key: keyof ParserSettings["postprocess"], checked: boolean) => {
    set({ postprocess: { ...settings.postprocess, [key]: checked } });
  };

  return (
    <div className="settings-grid">
      <section className="panel settings-card settings-card-wide">
        <h3>Общие настройки парсинга</h3>
        <Toggle
          checked={settings.enabled}
          onChange={(enabled) => set({ enabled })}
          label="Парсинг включён"
          hint="Глобально запрещает запуск новых задач парсинга для всех пользователей. Уже активные задачи не останавливает."
        />
        <div className="settings-form-grid">
          <NumberField label="Лимит по умолчанию" min={1} max={500} value={settings.default_limit} onChange={(default_limit) => set({ default_limit })} />
          <NumberField label="Максимальный лимит" min={1} max={5000} value={settings.max_limit} onChange={(max_limit) => set({ max_limit })} />
          <NumberField label="Таймаут parser_alpha, сек" min={30} max={7200} value={settings.subprocess_timeout_seconds} onChange={(subprocess_timeout_seconds) => set({ subprocess_timeout_seconds })} />
          <NumberField label="Retry источника" min={0} max={10} value={settings.retry_count} onChange={(retry_count) => set({ retry_count })} hint="Зарезервировано для следующего этапа: parser_alpha retry-policy." />
          <NumberField label="Пауза между retry, сек" min={0} max={600} value={settings.retry_delay_seconds} onChange={(retry_delay_seconds) => set({ retry_delay_seconds })} hint="Зарезервировано для следующего этапа." />
          <NumberField label="Макс. параллельных parse-задач" min={1} max={20} value={settings.max_parallel_parse_jobs} onChange={(max_parallel_parse_jobs) => set({ max_parallel_parse_jobs })} hint="Пока информативно: фактическая параллельность задают воркеры." />
        </div>
      </section>

      <section className="panel settings-card settings-card-wide">
        <h3>Источники</h3>
        <div className="settings-source-table">
          <div className="settings-source-head">Источник</div>
          <div className="settings-source-head">Включён</div>
          <div className="settings-source-head">Лимит</div>
          {sources.map((source) => (
            <div className="settings-source-row" key={source}>
              <strong>{source}</strong>
              <input
                type="checkbox"
                checked={settings.enabled_sources?.[source] ?? true}
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
                max={settings.max_limit || 100}
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
            </div>
          ))}
        </div>
      </section>

      <section className="panel settings-card settings-card-wide">
        <h3>Что делать после сохранения статьи</h3>
        <div className="settings-toggle-grid">
          {(Object.keys(POSTPROCESS_LABELS) as Array<keyof ParserSettings["postprocess"]>).map((key) => (
            <Toggle key={key} checked={settings.postprocess?.[key] ?? true} onChange={(checked) => setPostprocess(key, checked)} label={POSTPROCESS_LABELS[key]} />
          ))}
        </div>
      </section>

      <div className="settings-actions settings-card-wide">
        <button className="btn btn-primary" disabled={saving} onClick={onSave}>{saving ? "Сохранение..." : "Сохранить настройки парсера"}</button>
        <button className="btn" disabled={saving} onClick={onReset}>Сбросить раздел</button>
      </div>
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
            <span>{key}</span>
            <strong>{typeof item === "object" ? JSON.stringify(item) : String(item)}</strong>
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
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await settingsApi.getSystemSettings();
      setSettings(data.settings);
      setSchema(data.schema);
      setDraftParser(clone(data.settings.parser));
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

  async function saveParser() {
    if (!draftParser) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = await settingsApi.updateSystemSettingsSection("parser", draftParser);
      setSettings((prev) => (prev ? { ...prev, parser: result.value as ParserSettings } : prev));
      setDraftParser(result.value as ParserSettings);
      setMessage("Настройки парсера сохранены. Новые задачи будут использовать обновлённые значения.");
    } catch (err: any) {
      setError(err?.message || "Не удалось сохранить настройки");
    } finally {
      setSaving(false);
    }
  }

  async function resetParser() {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = await settingsApi.resetSystemSettingsSection("parser");
      setSettings((prev) => (prev ? { ...prev, parser: result.value as ParserSettings } : prev));
      setDraftParser(result.value as ParserSettings);
      setMessage("Настройки парсера сброшены к безопасным значениям.");
    } catch (err: any) {
      setError(err?.message || "Не удалось сбросить настройки");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page technical-settings-page">
      <div className="page-head">
        <div>
          <h2>Технический отдел — настройки</h2>
          <p className="muted">Глобальные настройки сайта. Они применяются ко всем пользователям и новым фоновых задачам.</p>
        </div>
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
            {section.title || TAB_LABELS[section.key] || section.key}
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
          onSave={saveParser}
          onReset={resetParser}
        />
      )}

      {!loading && activeTab === "pdf_markdown" && settings && (
        <JsonReadOnlyPanel title="PDF / Markdown" value={settings.pdf_markdown || {}} />
      )}
      {!loading && activeTab === "qwen" && settings && (
        <JsonReadOnlyPanel title="Qwen / AI" value={settings.qwen || {}} />
      )}
      {!loading && activeTab === "workers" && schema?.readonly?.workers && (
        <JsonReadOnlyPanel title="Очереди и воркеры — только просмотр" value={schema.readonly.workers} />
      )}
      {!loading && activeTab === "system" && schema?.readonly?.system && (
        <JsonReadOnlyPanel title="Система — только просмотр" value={schema.readonly.system} />
      )}
    </div>
  );
}
