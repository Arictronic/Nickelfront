import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  deletePaper,
  exportPaperReport,
  getPaperDetails,
  getPaperPdfBlobUrl,
  getPaperPdfUrl,
  getPaperReport,
  regeneratePaperContentPart,
  regeneratePaperMarkdownPages,
  reprocessPaperContent,
  translatePaperText,
} from "../api/papers";
import { getPublicDisplaySettings } from "../api/settings";
import { useToast } from "../components/ui/Toast";
import { useAuthStore } from "../store/authStore";
import type {
  Paper,
  PaperContentPart,
  PaperProcessingStatusInfo,
  PaperProcessingQualityInfo,
  PaperProcessingPipelineStatus,
  PaperRegenerationMode,
  PdfProcessingMode,
  PaperReportData,
} from "../types/paper";
import {
  getProcessingProgress,
  getProcessingStatusLabel,
  isPaperProcessing,
} from "../types/paper";

type Tab = "main" | "parts" | "report";
type BusyAction = "delete" | "reprocess" | null;
type ReportExportFormat = "pdf" | "docx";
type TextViewMode = "raw" | "ai";

type DisplayPartTranslation = {
  languageCode: string;
  languageName: string | null;
  text: string | null;
  status: string;
  error: string | null;
  translatedChars: number;
};

type PartLayerStatus = {
  key: string;
  label: string;
  tone: "neutral" | "pending" | "processing" | "success" | "warning" | "error";
  detail?: string;
};

type DisplayPart = {
  id: number | null;
  title: string;
  pageStart: number | null;
  pageEnd: number | null;
  markdown: string;
  rawText: string | null;
  status: string;
  error: string | null;
  regenerationCount: number;
  rawTextChars: number;
  markdownTextChars: number;
  extractionMethod: string | null;
  extractionQualityScore: number | null;
  extractionWarnings: string[];
  extractionMetadata: Record<string, unknown> | null;
  contentType: string | null;
  sectionTitle: string | null;
  sectionIndex: number | null;
  pageProfile: string | null;
  includeInEmbedding: boolean;
  translations: DisplayPartTranslation[];
  sourcePartIds: number[];
};

const RU = {
  invalidId: "Некорректный ID статьи",
  loading: "Загрузка статьи...",
  notFound: "Статья не найдена.",
  home: "Главная",
  papers: "Статьи",
  authors: "Авторы",
  source: "Источник",
  date: "Дата",
  journal: "Журнал",
  keywords: "Ключевые слова",
  language: "Язык статьи",
  status: "Статус обработки",
  fullText: "Полный текст",
  abstract: "Аннотация",
  allArticleData: "Все данные статьи",
  allArticleDataHint: "Развернуть технические данные записи",
  identifiers: "Идентификаторы",
  sourceId: "ID в источнике",
  canonicalPatentId: "Единый ID патента",
  canonicalPatentIdHint: "Нормализованный ID патента для склейки дублей из Rospatent, FreePatent, GooglePatents и PATENTSCOPE. Формируется из source_id или URL: убираются пробелы, дефисы, слэши, номер приводится к верхнему регистру; для RU-номеров добавляется/нормализуется префикс RU.",
  createdAt: "Добавлена",
  updatedAt: "Обновлена",
  fileProcessingQuality: "Качество обработки файла",
  fileProcessingQualityEmpty: "Нет данных обработки файла",
  metadataParseConfidence: "Уверенность метаданных",
  metadataParseConfidenceHint: "Это оценка полноты метаданных записи при первичном парсинге источника: название, авторы, дата, аннотация, source_id, URL/PDF. Это не качество распознавания PDF.",
  schemaVersion: "Версия схемы",
  qualityFlags: "Флаги качества записи",
  qualityFlagsHint: "Это замечания парсера к метаданным и источникам записи: отсутствующие поля, резервные источники или деградация извлечения. Это не отдельная ошибка PDF-пайплайна.",
  provenance: "Происхождение полей",
  pdfUrl: "PDF URL",
  pdfLocalPath: "Локальный PDF",
  contentPartsMeta: "Сохранённые части документа",
  contentPartsCount: "Количество частей",
  rawChars: "Символов текста из файла",
  aiChars: "Символов текста после ИИ",
  embeddingParts: "Частей для векторного индекса",
  noQualityFlags: "Флагов качества нет.",
  noProvenance: "Данных provenance нет.",
  yes: "Есть",
  no: "Нет",
  open: "Открыть",
  openPdf: "Открыть PDF",
  workerTask: "Задача Celery",
  tabMain: "Главная",
  tabParts: "Текст по страницам",
  tabReport: "Отчёт",
  gist: "Суть статьи",
  gistNotReady: "Здесь будет короткий пересказ всего документа: о чём он, какие ключевые результаты и почему он полезен для анализа.",
  pdfLen: "PDF",
  pdfLoading: "PDF загружается...",
  pdfLoadError: "PDF недоступен",
  pdfPreviewReady: "PDF сохранён локально, предпросмотр ещё не загружен",
  loadPdfPreview: "Показать PDF",
  pdfNotCached: "PDF-ссылка есть, но файл ещё не сохранён локально. Запустите обработку документа, чтобы скачать PDF через очередь.",
  queuePdfProcessing: "Поставить PDF в очередь",
  articleText: "Текст статьи",
  translateArticleText: "Перевести текст статьи",
  translatingArticleText: "Переводится...",
  textLanguage: "Язык текста",
  translateTarget: "Перевести на",
  originalTextLanguage: "Оригинал",
  translationPending: "Перевод этой страницы ещё выполняется.",
  translationMissing: "Для этой страницы перевод на выбранный язык ещё не готов.",
  translationQueued: "Перевод текста статьи поставлен в очередь.",
  translationError: "Не удалось поставить перевод текста статьи в очередь",
  translationStatus: "Статус перевода",
  translationForce: "Перевести заново",
  translationForceHint: "Перезаписать уже готовые страницы выбранного языка",
  translationReady: "готово",
  translationFailed: "ошибка",
  translationMissingShort: "нет",
  translationSameLanguage: "Целевой язык совпадает с языком оригинала",
  reportTitle: "Отчёт по статье",
  reportLoadError: "JSON-отчёт не загрузился. Показаны доступные данные статьи.",
  exportPdf: "Экспорт PDF",
  exportDocx: "Экспорт DOCX",
  exporting: "Экспорт...",
  reprocessBtn: "Перезапустить обработку всего документа",
  parts: "Текст по страницам",
  emptyText: "Текст пуст.",
  selectedPart: "Выбранная страница",
  processingError: "Ошибка обработки",
  noTextForReport: "Нет данных для отчёта.",
  symbols: "символов",
  deletePaper: "Удалить статью",
  copyGist: "Копировать суть",
  backToList: "Назад к списку",
  copied: "Скопировано!",
  copyEmpty: "Суть статьи ещё не готова — копировать нечего.",
  deleteOk: "Статья удалена.",
  deleteError: "Не удалось удалить статью",
  reprocessQueued: "Повторная обработка поставлена в очередь.",
  reprocessError: "Не удалось перезапустить обработку",
  regenerateQueued: "Перегенерация страницы поставлена в очередь.",
  regenerateError: "Не удалось перегенерировать страницу",
  regenerate: "Перегенерировать",
  regenerateMode: "Режим",
  regenerateModeText: "По тексту",
  regenerateModeImage: "По фото",
  regenerateModeTextHint: "Берёт сохранённый исходный текст части",
  regenerateModeImageHint: "Рендерит страницу PDF как изображение и отправляет её в Qwen",
  pdfMode: "Режим PDF",
  pdfModeAuto: "Auto — обычный",
  pdfModeAutoHint: "Обычные алгоритмы извлечения текста и fallback без принудительного AI по фото",
  pdfModeMypdf: "MyPDF — быстрый текст",
  pdfModeMypdfHint: "Быстро берёт текстовый слой PDF через PyMuPDF: без OCR, фото и таблиц",
  pdfModeAi: "AI — по фото",
  pdfModeAiHint: "Рендерит страницы PDF как изображения и отправляет в Qwen",
  regenerating: "Перегенерация...",
  actionInProgress: "Выполняется...",
  rawText: "Текст из файла",
  markdownText: "Текст после ИИ",
  textFromFile: "Текст из файла",
  textAfterAi: "Текст после ИИ",
  rawLayer: "Текст из файла",
  aiLayer: "Текст после ИИ",
  rawNotAvailable: "Текст из файла недоступен.",
  aiNotAvailable: "Текст после ИИ ещё не готов.",
  partsStatus: "Статус частей",
  quality: "Целостность",
  extractionDiagnostics: "Диагностика извлечения",
  extractionDiagnosticsHidden: "Диагностика извлечения скрыта настройками.",
  noStoredParts: "Сохранённых страниц пока нет. Показываю старое разбиение полного текста.",
  contentPartsLoadError: "Не удалось загрузить сохранённые страницы/части документа. Показываю общий текст, если он есть.",
  adminOnlyRegenerate: "Перегенерация страниц доступна только администратору.",
  confirmDelete: "Удалить статью из базы?",
  unknown: "—",
};

const LEGACY_PAGE_BLOCK_RE = /(?:^|\n)\s*#{1,6}\s*(?:Pages|Страницы?)\s+(\d+)(?:\s*-\s*(\d+))?[^\n]*\n+/gi;

function isMarkdownStructuralLine(line: string): boolean {
  const value = line.trim();
  if (!value) return true;
  return (
    /^(```|~~~)/.test(value) ||
    /^(#{1,6}\s+)/.test(value) ||
    /^([-*+]\s+|\d+[.)]\s+)/.test(value) ||
    /^>\s?/.test(value) ||
    /^\|.*\|$/.test(value) ||
    /^\$\$/.test(value) ||
    /^\[[^\]]*(table|formula|page)[^\]]*\]/i.test(value)
  );
}

function reflowSoftLineBreaks(text: string): string {
  const value = (text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const blocks = value.split(/\n{2,}/);

  return blocks
    .map((block) => {
      const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
      if (!lines.length) return "";
      if (lines.some(isMarkdownStructuralLine)) return lines.join("\n");

      return lines.reduce((acc, line) => {
        if (!acc) return line;
        if (/[-‐‑‒–—]$/.test(acc)) return acc.replace(/[-‐‑‒–—]$/, "") + line;
        return `${acc} ${line}`;
      }, "");
    })
    .filter(Boolean)
    .join("\n\n");
}

function normalizeMarkdownForDisplay(text: string): string {
  let value = (text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  if (!value) return "";

  value = value.replace(/^```(?:markdown|md)?\s*/i, "").replace(/\s*```$/i, "").trim();
  value = value.replace(/\\\((.+?)\\\)/gs, (_, body: string) => `$${body.trim()}$`);
  value = value.replace(/\\\[(.+?)\\\]/gs, (_, body: string) => `$$\n${body.trim()}\n$$`);
  value = value.replace(/([^\n])\s+(#{1,6}\s+)/g, "$1\n\n$2");
  value = reflowSoftLineBreaks(value);
  value = value.replace(/\n{3,}/g, "\n\n");
  return value;
}


function pageTitle(pageStart: number | null, pageEnd: number | null, fallback: string): string {
  if (!pageStart || !pageEnd) return fallback;
  if (pageStart === pageEnd) return `Страница ${pageStart}`;
  return `Страницы ${pageStart}-${pageEnd}`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return RU.unknown;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU");
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return RU.unknown;
  const normalized = Number(value) <= 1 ? Number(value) * 100 : Number(value);
  return `${Math.max(0, Math.min(100, Math.round(normalized)))}%`;
}

function formatPaperLanguage(paper: Paper): string {
  const name = (paper.languageName || "").trim();
  const code = (paper.languageCode || "").trim();
  const base = name && name !== "Не определён" ? name : code && code !== "unknown" ? code : RU.unknown;
  if (base === RU.unknown) return base;
  if (typeof paper.languageConfidence === "number" && Number.isFinite(paper.languageConfidence)) {
    return `${base} · ${formatPercent(paper.languageConfidence)}`;
  }
  return base;
}

function nonEmptyEntries(record: Record<string, string> | null | undefined): [string, string][] {
  return Object.entries(record ?? {}).filter(([key, value]) => Boolean(key.trim() || String(value ?? "").trim()));
}

function FieldList({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <div className="detail-grid">
      {rows.map(([label, value]) => (
        <p key={label}><strong>{label}:</strong> {value || RU.unknown}</p>
      ))}
    </div>
  );
}

function FieldValueWithHint({ value, hint }: { value: ReactNode; hint: string }) {
  return (
    <span className="field-value-with-hint">
      <span>{value || RU.unknown}</span>
      <small>{hint}</small>
    </span>
  );
}

function splitLegacyMarkdownParts(text: string): DisplayPart[] {
  const value = (text || "").trim();
  if (!value) return [];

  const matches = [...value.matchAll(LEGACY_PAGE_BLOCK_RE)];
  if (matches.length) {
    return matches
      .map((match, idx) => {
        const start = (match.index ?? 0) + match[0].length;
        const end = idx + 1 < matches.length ? matches[idx + 1].index ?? value.length : value.length;
        const pageStart = Number(match[1]);
        const pageEnd = Number(match[2] || match[1]);
        const markdown = value.slice(start, end).trim();
        return {
          id: null,
          title: pageTitle(pageStart, pageEnd, `Часть ${idx + 1}`),
          pageStart,
          pageEnd,
          markdown,
          rawText: null,
          status: "legacy",
          error: null,
          regenerationCount: 0,
          rawTextChars: 0,
          markdownTextChars: markdown.length,
          extractionMethod: null,
          extractionQualityScore: null,
          extractionWarnings: [],
          extractionMetadata: null,
          contentType: null,
          sectionTitle: null,
          sectionIndex: null,
          pageProfile: null,
          includeInEmbedding: true,
          translations: [],
          sourcePartIds: [],
        };
      })
      .filter((part) => part.markdown.trim().length > 0);
  }

  const chunkSize = 4500;
  const chunks: DisplayPart[] = [];
  for (let i = 0; i < value.length; i += chunkSize) {
    const markdown = value.slice(i, i + chunkSize).trim();
    if (!markdown) continue;
    chunks.push({
      id: null,
      title: `Часть ${chunks.length + 1}`,
      pageStart: null,
      pageEnd: null,
      markdown,
      rawText: null,
      status: "legacy",
      error: null,
      regenerationCount: 0,
      rawTextChars: 0,
      markdownTextChars: markdown.length,
      extractionMethod: null,
      extractionQualityScore: null,
      extractionWarnings: [],
      extractionMetadata: null,
      contentType: null,
      sectionTitle: null,
      sectionIndex: null,
      pageProfile: null,
      includeInEmbedding: true,
      translations: [],
      sourcePartIds: [],
    });
  }
  return chunks;
}


function findFallbackMarkdownForPages(
  fallbackParts: DisplayPart[],
  pageStart: number | null,
  pageEnd: number | null,
  orderIndex: number,
): string | null {
  if (!fallbackParts.length) return null;

  if (pageStart && pageEnd) {
    const exact = fallbackParts.find((part) => part.pageStart === pageStart && part.pageEnd === pageEnd);
    if (exact?.markdown.trim()) return exact.markdown;

    const covering = fallbackParts.find((part) => {
      if (!part.pageStart || !part.pageEnd) return false;
      return part.pageStart <= pageStart && part.pageEnd >= pageEnd;
    });
    if (covering?.markdown.trim()) return covering.markdown;
  }

  const byOrder = fallbackParts[orderIndex];
  return byOrder?.markdown.trim() ? byOrder.markdown : null;
}

function mapPartTranslations(part: PaperContentPart): DisplayPartTranslation[] {
  return (part.translations ?? []).map((translation) => ({
    languageCode: (translation.languageCode || "").trim().toLowerCase(),
    languageName: translation.languageName ?? null,
    text: translation.translatedMarkdownText ?? null,
    status: translation.status ?? "pending",
    error: translation.error ?? null,
    translatedChars: translation.translatedChars ?? translation.translatedMarkdownText?.length ?? 0,
  })).filter((translation) => Boolean(translation.languageCode));
}

function mergePartTranslations(parts: PaperContentPart[]): DisplayPartTranslation[] {
  const groups = new Map<string, DisplayPartTranslation[]>();
  for (const part of parts) {
    for (const translation of mapPartTranslations(part)) {
      const current = groups.get(translation.languageCode) ?? [];
      current.push(translation);
      groups.set(translation.languageCode, current);
    }
  }

  return Array.from(groups.entries()).map(([languageCode, items]) => {
    const texts = items.map((item) => item.text?.trim() ?? "").filter(Boolean);
    const statuses = items.map((item) => item.status);
    const status = statuses.every((item) => item === "ready")
      ? "ready"
      : statuses.includes("processing")
        ? "processing"
        : statuses.includes("ready")
          ? "partial"
          : statuses.includes("failed")
            ? "failed"
            : statuses[0] ?? "pending";
    const errors = items.map((item) => item.error?.trim() ?? "").filter(Boolean);
    return {
      languageCode,
      languageName: items.find((item) => item.languageName)?.languageName ?? null,
      text: texts.length ? texts.join("\n\n") : null,
      status,
      error: errors.length ? errors.join("\n") : null,
      translatedChars: texts.join("\n\n").length,
    };
  });
}

function getPartTranslation(part: DisplayPart, languageCode: string): DisplayPartTranslation | null {
  const normalized = (languageCode || "").trim().toLowerCase();
  if (!normalized) return null;
  return part.translations.find((translation) => translation.languageCode === normalized) ?? null;
}

function languageLabel(code: string, paper?: Paper | null, fallbackName?: string | null): string {
  const normalized = (code || "").trim().toLowerCase();
  if (!normalized || normalized === "original") return RU.originalTextLanguage;
  if (fallbackName?.trim()) return fallbackName.trim();
  if (paper && normalized === (paper.languageCode || "").trim().toLowerCase()) {
    return paper.languageName || normalized.toUpperCase();
  }
  const labels: Record<string, string> = {
    ru: "Русский",
    en: "English",
    de: "Deutsch",
    fr: "Français",
    es: "Español",
    zh: "中文",
  };
  return labels[normalized] ?? normalized.toUpperCase();
}


function mapStoredPart(part: PaperContentPart, fallbackMarkdown: string | null = null): DisplayPart {
  const title = pageTitle(part.pageStart, part.pageEnd, `Часть ${part.partIndex}`);
  const markdown = part.markdownText?.trim() || fallbackMarkdown?.trim() || "";
  return {
    id: part.id,
    title,
    pageStart: part.pageStart,
    pageEnd: part.pageEnd,
    markdown,
    rawText: part.rawText,
    status: part.status,
    error: part.error,
    regenerationCount: part.regenerationCount,
    rawTextChars: part.rawTextChars,
    markdownTextChars: part.markdownTextChars,
    extractionMethod: part.extractionMethod ?? null,
    extractionQualityScore: part.extractionQualityScore ?? null,
    extractionWarnings: part.extractionWarnings ?? [],
    extractionMetadata: part.extractionMetadata ?? null,
    contentType: part.contentType ?? null,
    sectionTitle: part.sectionTitle ?? null,
    sectionIndex: part.sectionIndex ?? null,
    pageProfile: part.pageProfile ?? null,
    includeInEmbedding: part.includeInEmbedding ?? true,
    translations: mapPartTranslations(part),
    sourcePartIds: [part.id],
  };
}

function mergePartStatus(parts: PaperContentPart[]): string {
  const statuses = parts.map((part) => normalizePartStatus(part.status));

  if (statuses.includes("processing")) return "processing";
  if (statuses.includes("failed")) return "failed";
  if (statuses.every((status) => status === "ready")) return "ready";
  if (statuses.includes("raw_extracted")) return "raw_extracted";
  if (statuses.includes("ready")) return "ready";

  return parts[0]?.status ?? "raw_extracted";
}

function averageQuality(parts: PaperContentPart[]): number | null {
  const scores = parts
    .map((part) => part.extractionQualityScore)
    .filter((score): score is number => score !== null && score !== undefined && !Number.isNaN(Number(score)))
    .map((score) => Number(score));

  if (!scores.length) return null;
  return scores.reduce((sum, value) => sum + value, 0) / scores.length;
}

function mergeExtractionMethod(parts: PaperContentPart[]): string | null {
  const methods = Array.from(
    new Set(
      parts
        .map((part) => part.extractionMethod)
        .filter((method): method is string => Boolean(method?.trim())),
    ),
  );

  if (!methods.length) return null;
  if (methods.length === 1) return methods[0];
  return "mixed";
}

function aggregateStoredPartsByPage(parts: PaperContentPart[], fallbackParts: DisplayPart[] = []): DisplayPart[] {
  const groups = new Map<string, PaperContentPart[]>();

  for (const part of parts) {
    const key = `${part.pageStart}-${part.pageEnd}`;
    const current = groups.get(key) ?? [];
    current.push(part);
    groups.set(key, current);
  }

  return Array.from(groups.values()).map((group) => {
    const first = group[0];

    if (group.length === 1) {
      const fallbackMarkdown = findFallbackMarkdownForPages(fallbackParts, first.pageStart, first.pageEnd, first.partIndex - 1);
      return mapStoredPart(first, fallbackMarkdown);
    }

    const rawText = group
      .map((part) => part.rawText?.trim() ?? "")
      .filter(Boolean)
      .join("\n\n");

    const markdownFromParts = group
      .map((part) => part.markdownText?.trim() ?? "")
      .filter(Boolean)
      .join("\n\n");
    const fallbackMarkdown = findFallbackMarkdownForPages(fallbackParts, first.pageStart, first.pageEnd, first.partIndex - 1);
    const markdown = markdownFromParts || fallbackMarkdown || "";

    const errors = group
      .map((part) => part.error?.trim() ?? "")
      .filter(Boolean);

    const warnings = Array.from(new Set(group.flatMap((part) => part.extractionWarnings ?? [])));
    const sourcePartIds = group.map((part) => part.id);

    return {
      id: null,
      title: pageTitle(first.pageStart, first.pageEnd, `Часть ${first.partIndex}`),
      pageStart: first.pageStart,
      pageEnd: first.pageEnd,
      markdown,
      rawText,
      status: mergePartStatus(group),
      error: errors.length ? errors.join("\n") : null,
      regenerationCount: group.reduce((sum, part) => sum + Number(part.regenerationCount || 0), 0),
      rawTextChars: rawText.length,
      markdownTextChars: markdown.length,
      extractionMethod: mergeExtractionMethod(group),
      extractionQualityScore: averageQuality(group),
      extractionWarnings: warnings,
      extractionMetadata: {
        aggregatedByPage: true,
        sourcePartIds,
        sourcePartsCount: group.length,
        pageStart: first.pageStart,
        pageEnd: first.pageEnd,
      },
      contentType: "body",
      sectionTitle: first.sectionTitle ?? null,
      sectionIndex: first.sectionIndex ?? null,
      pageProfile: first.pageProfile ?? null,
      includeInEmbedding: group.some((part) => part.includeInEmbedding),
      translations: mergePartTranslations(group),
      sourcePartIds,
    };
  });
}

function getRegenerationKey(part: DisplayPart | null): string | null {
  if (!part) return null;
  const sourcePartIds = Array.from(new Set(part.sourcePartIds.filter((id) => Number.isFinite(id))));
  if (sourcePartIds.length > 1) return `parts-${sourcePartIds.join("-")}`;
  if (part.id) return `part-${part.id}`;
  if (part.pageStart && part.pageEnd) return `pages-${part.pageStart}-${part.pageEnd}`;
  return null;
}



function normalizePartStatus(status: string | null | undefined): string {
  return (status || "").trim().toLowerCase();
}

const PDF_WARNING_LABELS: Record<string, string> = {
  ai_disabled: "AI-распознавание отключено",
  ai_empty_response: "AI вернул пустой текст",
  ai_page_recognition_failed: "AI не распознал страницу",
  ai_replacement_session_used: "AI-сессия была пересоздана",
  cross_page_continuation_moved: "перенос текста на соседнюю страницу",
  cross_page_continuation_repaired: "склейка разрыва между страницами",
  headers_footers_removed: "удалены повторяющиеся колонтитулы",
  low_text_density: "мало текста",
  possible_scan: "возможный скан",
  scanned_page: "сканированная страница",
  ocr_used: "OCR",
  ocr_dependencies_missing: "OCR недоступен",
  possible_two_columns: "две колонки",
  tables_detected: "таблицы",
  table_extraction_failed: "таблицы извлечены не полностью",
  noisy_text: "шумный текст",
  many_control_chars: "служебные символы",
  short_page: "короткая страница",
  empty_page: "пустая страница",
  extraction_failed: "текст не извлечён",
};

const CONTENT_TYPE_LABELS: Record<string, string> = {
  body: "основной текст",
  heading: "заголовок",
  caption: "подпись",
  formula: "формулы",
  table: "таблицы",
  reference: "список литературы",
  footnote: "сноски",
  affiliation: "аффилиация",
  abstract: "аннотация",
};

const EXTRACTION_METHOD_LABELS: Record<string, string> = {
  auto: "авто",
  pdfplumber_auto: "авто",
  pdfplumber_layout: "layout-режим",
  pdfplumber_simple: "простой режим",
  pdfplumber_columns: "двухколоночный режим",
  columns: "двухколоночный режим",
  layout: "layout-режим",
  simple: "простой режим",
  ocr: "OCR",
  mypdf_text_layer: "MyPDF: текстовый слой",
  simple_text_layer_fallback: "резервный текстовый слой",
  ai_page_image: "AI: страница как изображение",
  ai_page_image_regenerate: "AI: перегенерация по фото",
};

const QUALITY_FLAG_LABELS: Record<string, string> = {
  metadata_missing_authors: "Не найдены авторы",
  metadata_missing_publication_date: "Не найдена дата публикации",
  metadata_missing_abstract: "Не найдена аннотация",
  metadata_missing_source_id: "Не найден ID в источнике",
  pdf_url_available: "PDF-ссылка есть",
  pdf_url_verified: "PDF-ссылка проверена",
  pdf_url_unverified: "PDF-ссылка не проверена",
  pdf_url_via_openalex_content_api: "PDF-ссылка найдена через OpenAlex Content API",
  pdf_url_resolved_from_detail: "PDF-ссылка найдена со страницы источника",
  full_text_available: "Полный текст доступен",
  full_text_extracted_from_detail: "Полный текст извлечён со страницы источника",
  content_access_unresolved: "Доступ к полному тексту не определён",
  full_text_missing: "Полный текст не найден",
  pdf_download_failed: "PDF не загрузился",
  pdf_unavailable: "PDF недоступен",
  mypdf_fallback_used: "MyPDF сработал через резервный метод",
  ai_fields_stale_after_text_update: "AI-анализ устарел после обновления текста",
  keywords_stale_after_text_update: "Ключевые слова устарели после обновления текста",
};

const QUALITY_FLAG_HINTS: Record<string, string> = {
  metadata_missing_authors: "Источник не вернул список авторов или парсер не смог его нормализовать.",
  metadata_missing_publication_date: "Источник не вернул дату публикации или дата не прошла нормализацию.",
  metadata_missing_abstract: "Источник не вернул аннотацию; она может появиться только после отдельной обработки полного текста.",
  metadata_missing_source_id: "У записи нет стабильного ID источника, поэтому хуже работает дедупликация.",
  pdf_url_available: "В записи есть ссылка на PDF, но это ещё не означает, что файл уже скачан локально.",
  pdf_url_verified: "Парсер проверил, что ссылка ведёт на доступный PDF или PDF-подобный ресурс.",
  pdf_url_unverified: "Ссылка на PDF получена из источника, но проверка доступности не была выполнена или не дала уверенного результата.",
  pdf_url_via_openalex_content_api: "Официальная PDF-ссылка была добрана дополнительным запросом к OpenAlex Content API.",
  pdf_url_resolved_from_detail: "Парсер открыл страницу записи и нашёл PDF-ссылку внутри карточки источника.",
  full_text_available: "Источник вернул полный текст или достаточный текстовый payload без отдельного PDF-пайплайна.",
  full_text_extracted_from_detail: "Полный текст был получен не из PDF, а из HTML/detail-страницы источника.",
  content_access_unresolved: "Парсер не смог уверенно определить, доступен ли полный текст или PDF для этой записи.",
  full_text_missing: "После парсинга источника полный текст у записи отсутствует.",
  pdf_download_failed: "Ссылка была, но скачивание PDF завершилось ошибкой.",
  pdf_unavailable: "Источник не дал рабочий PDF или доступ к файлу закрыт.",
  mypdf_fallback_used: "Быстрый PyMuPDF/MyPDF не смог штатно извлечь текст, поэтому использован резервный локальный текстовый слой. В UI режим всё равно остаётся MyPDF = 80%.",
  ai_fields_stale_after_text_update: "Полный текст был заменён или страница была переоцифрована. Старые summary/analysis/translation нельзя считать актуальными до новой Qwen-обработки.",
  keywords_stale_after_text_update: "Полный текст был заменён или страница была переоцифрована. Ключевые слова нужно заново проверить по актуальному тексту документа.",
};

function warningLabel(warning: string): string {
  const key = (warning || "").trim();
  return PDF_WARNING_LABELS[key] ?? key.replace(/_/g, " ");
}

function methodLabel(method: string | null | undefined): string | null {
  const key = (method || "").trim();
  if (!key) return null;
  return EXTRACTION_METHOD_LABELS[key] ?? key.replace(/_/g, " ");
}

function contentTypeLabel(contentType: string | null | undefined): string | null {
  const key = (contentType || "").trim();
  if (!key) return null;
  return CONTENT_TYPE_LABELS[key] ?? key.replace(/_/g, " ");
}

function formatQuality(score: number | null | undefined): string | null {
  if (score === null || score === undefined || Number.isNaN(Number(score))) return null;
  const value = Number(score);
  const percent = value <= 1 ? value * 100 : value;
  return `${Math.max(0, Math.min(100, Math.round(percent)))}%`;
}

function qualityFlagLabel(flag: string): string {
  const key = (flag || "").trim();
  return QUALITY_FLAG_LABELS[key] ?? PDF_WARNING_LABELS[key] ?? `Флаг парсера: ${key.replace(/_/g, " ")}`;
}

function qualityFlagHint(flag: string): string | undefined {
  const key = (flag || "").trim();
  return QUALITY_FLAG_HINTS[key];
}

function metadataString(metadata: Record<string, unknown> | null | undefined, key: string): string {
  const value = metadata?.[key];
  if (typeof value === "string") return value.trim().toLowerCase();
  if (typeof value === "number" || typeof value === "boolean") return String(value).trim().toLowerCase();
  return "";
}

function detectFileProcessingMode(parts: PaperContentPart[]): PdfProcessingMode | "unknown" {
  const signals = parts.map((part) => [
    part.extractionMethod || "",
    metadataString(part.extractionMetadata, "parser_mode"),
    metadataString(part.extractionMetadata, "extraction_mode"),
    metadataString(part.extractionMetadata, "force_strategy"),
    metadataString(part.extractionMetadata, "selected_strategy"),
    metadataString(part.extractionMetadata, "primary_selected_strategy"),
    metadataString(part.extractionMetadata, "extraction_strategy"),
  ].join(" ").toLowerCase());

  if (signals.some((signal) => /(^|[^a-z])ai([^a-z]|$)|ai_page_image/.test(signal))) return "ai";
  if (signals.some((signal) => signal.includes("mypdf"))) return "mypdf";
  return parts.length ? "auto" : "unknown";
}

function fileProcessingQualitySummary(
  parts: PaperContentPart[],
  backendQuality: PaperProcessingQualityInfo | null,
): { value: string; hint: string } {
  if (backendQuality?.label) {
    return {
      value: backendQuality.label,
      hint: backendQuality.basis || "Качество рассчитано backend по сохранённым частям документа.",
    };
  }

  const usableParts = parts.filter((part) => (part.rawTextChars || part.rawText?.trim() || part.extractionQualityScore !== null));
  const mode = detectFileProcessingMode(usableParts);
  if (!usableParts.length || mode === "unknown") {
    return {
      value: RU.fileProcessingQualityEmpty,
      hint: "Качество появится после завершения обработки PDF и сохранения частей документа.",
    };
  }

  if (mode === "mypdf") {
    return {
      value: "MyPDF — 80%",
      hint: "MyPDF берёт только текстовый слой PDF без OCR, фото и восстановления таблиц, поэтому для этого режима фиксируется 80%.",
    };
  }

  const normalizedScores = usableParts
    .map((part) => part.extractionQualityScore)
    .filter((score): score is number => score !== null && score !== undefined && !Number.isNaN(Number(score)))
    .map((score) => (score <= 1 ? score * 100 : score));

  if (mode === "ai") {
    if (!normalizedScores.length) {
      return {
        value: "AI — качество ещё не рассчитано",
        hint: "AI-режим показывает 100% только после успешного распознавания всех страниц и сохранения page-level quality_score.",
      };
    }
    const score = Math.round(normalizedScores.reduce((sum, value) => sum + value, 0) / normalizedScores.length);
    return {
      value: `AI — ${Math.max(0, Math.min(100, score))}%`,
      hint: "AI-режим считается по сохранённым page-level score: 100% только если все страницы успешно распознаны через Qwen.",
    };
  }

  if (!normalizedScores.length) {
    return {
      value: "Auto — качество ещё не рассчитано",
      hint: "Auto должен показывать качество после отработки локального PDF-парсера, но у сохранённых частей пока нет extraction_quality_score.",
    };
  }

  const avg = Math.round(normalizedScores.reduce((sum, value) => sum + value, 0) / normalizedScores.length);
  return {
    value: `Auto — ${Math.max(0, Math.min(100, avg))}%`,
    hint: "Auto показывает среднее качество extraction_quality_score по сохранённым частям после локального PDF-парсера.",
  };
}

function getRawPartStatus(part: DisplayPart | null): PartLayerStatus {
  if (!part) return { key: "none", label: "В очереди", tone: "neutral" };
  const status = normalizePartStatus(part.status);
  const quality = formatQuality(part.extractionQualityScore);
  const method = methodLabel(part.extractionMethod);
  const detail = [quality ? `${RU.quality}: ${quality}` : null, method ? `метод: ${method}` : null]
    .filter(Boolean)
    .join(" · ");

  if (part.rawText?.trim()) {
    return { key: "raw_ready", label: "Готово", tone: "success", detail };
  }

  if (["processing", "extracting", "extracting_pdf_text"].includes(status)) {
    return { key: "raw_processing", label: "В обработке", tone: "processing", detail };
  }
  if (status === "failed" || part.error) {
    return { key: "raw_unavailable", label: "В очереди", tone: "pending", detail: part.error || detail };
  }
  if (["raw_extracted", "ready"].includes(status) && !part.rawText?.trim()) {
    return { key: "raw_empty", label: "В очереди", tone: "pending", detail };
  }
  if (status === "legacy") return { key: "raw_legacy", label: "В очереди", tone: "neutral" };
  return { key: "raw_pending", label: "В очереди", tone: "pending" };
}

function getAiPartStatus(part: DisplayPart | null): PartLayerStatus {
  if (!part) return { key: "none", label: "В очереди", tone: "neutral" };
  const status = normalizePartStatus(part.status);
  if (part.markdown?.trim()) {
    return { key: "ai_ready", label: "Готово", tone: "success" };
  }
  if (status === "processing") return { key: "ai_processing", label: "В обработке", tone: "processing" };
  if (status === "failed" || part.error) return { key: "ai_pending_after_error", label: "В очереди", tone: "pending", detail: part.error || undefined };
  if (status === "raw_extracted") return { key: "ai_waiting_raw", label: "В очереди", tone: "pending" };
  if (status === "ready" && !part.markdownTextChars) return { key: "ai_skipped", label: "В очереди", tone: "neutral" };
  if (status === "legacy" && part.markdown?.trim()) return { key: "ai_legacy", label: "Готово", tone: "success" };
  return { key: "ai_pending", label: "В очереди", tone: "pending" };
}

function getTranslationPartStatus(part: DisplayPart | null, languageCode: string): PartLayerStatus {
  if (!part) return { key: "translation_none", label: "В очереди", tone: "neutral" };
  const translation = getPartTranslation(part, languageCode);
  if (translation?.text?.trim()) {
    if (translation.status === "failed") return { key: "translation_ready_with_error", label: "Частично", tone: "warning", detail: translation.error || undefined };
    return { key: "translation_ready", label: "Готово", tone: "success" };
  }
  if (translation?.status === "processing") return { key: "translation_processing", label: "В обработке", tone: "processing", detail: translation.error || undefined };
  if (translation?.status === "failed") return { key: "translation_failed", label: "Ошибка", tone: "error", detail: translation.error || undefined };
  return { key: "translation_missing", label: "В очереди", tone: "pending" };
}

type TranslationSummary = {
  total: number;
  ready: number;
  processing: number;
  failed: number;
  missing: number;
};

function getTranslationSummary(parts: DisplayPart[], languageCode: string): TranslationSummary {
  const total = parts.length;
  let ready = 0;
  let processing = 0;
  let failed = 0;
  let missing = 0;

  for (const part of parts) {
    const translation = getPartTranslation(part, languageCode);
    if (translation?.text?.trim()) {
      ready += 1;
      continue;
    }
    if (translation?.status === "processing") {
      processing += 1;
      continue;
    }
    if (translation?.status === "failed") {
      failed += 1;
      continue;
    }
    missing += 1;
  }

  return { total, ready, processing, failed, missing };
}

function getOverallTranslationStatus(parts: DisplayPart[], languageCode: string): PartLayerStatus {
  const summary = getTranslationSummary(parts, languageCode);
  if (!summary.total) return { key: "translation_empty", label: "В очереди", tone: "neutral" };
  const detail = `${summary.ready}/${summary.total} частей готово`;
  if (summary.processing > 0) return { key: "translation_processing", label: `${summary.ready}/${summary.total}`, tone: "processing", detail };
  if (summary.failed > 0 && summary.ready === 0) return { key: "translation_failed", label: "Ошибка", tone: "error", detail };
  if (summary.failed > 0 || summary.missing > 0) return { key: "translation_partial", label: `${summary.ready}/${summary.total}`, tone: "warning", detail };
  return { key: "translation_ready", label: "Готово", tone: "success", detail };
}

function formatTranslationSummary(summary: TranslationSummary): string {
  if (!summary.total) return "Нет страниц для перевода";
  const chunks = [`${summary.ready}/${summary.total} ${RU.translationReady}`];
  if (summary.processing) chunks.push(`${summary.processing} в работе`);
  if (summary.failed) chunks.push(`${summary.failed} ${RU.translationFailed}`);
  if (summary.missing) chunks.push(`${summary.missing} ${RU.translationMissingShort}`);
  return chunks.join(" · ");
}

function integrityLabel(score: number | null): string {
  if (score === null || Number.isNaN(score)) return "не оценена";
  if (score >= 80) return "высокая";
  if (score >= 55) return "средняя";
  return "низкая";
}

function getOverallLayerStatus(parts: DisplayPart[], mode: TextViewMode): PartLayerStatus {
  if (!parts.length) return { key: "empty", label: "В очереди", tone: "neutral" };
  const statuses = parts.map((part) => (mode === "raw" ? getRawPartStatus(part) : getAiPartStatus(part)));
  const total = statuses.length;
  const ready = statuses.filter((s) => s.tone === "success").length;
  const processing = statuses.filter((s) => s.tone === "processing").length;

  if (mode === "raw") {
    const scores = parts
      .map((part) => part.extractionQualityScore)
      .filter((score): score is number => score !== null && score !== undefined && !Number.isNaN(Number(score)))
      .map((score) => (score <= 1 ? score * 100 : score));
    const avg = scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : null;
    const detail = avg !== null
      ? `целостность текста: ${integrityLabel(avg)} · среднее качество ${Math.round(avg)}%`
      : "целостность текста: не оценена";

    if (processing) return { key: "processing", label: "В обработке", tone: "processing", detail };
    if (ready === total) return { key: "ready", label: "Готово", tone: "success", detail };
    return { key: "pending", label: "В очереди", tone: "pending", detail };
  }

  if (processing) return { key: "processing", label: "В обработке", tone: "processing" };
  if (ready === total) return { key: "ready", label: "Готово", tone: "success" };
  return { key: "pending", label: "В очереди", tone: "pending" };
}

function StatusPill({ status }: { status: PartLayerStatus }) {
  return (
    <span className={`status-pill status-pill-${status.tone}`} title={status.detail || undefined}>
      {status.label}
    </span>
  );
}

function pipelineTone(status: string): PartLayerStatus["tone"] {
  if (status === "success") return "success";
  if (status === "error") return "error";
  if (status === "warning") return "warning";
  if (status === "processing") return "processing";
  if (status === "pending") return "pending";
  return "neutral";
}

function ProcessingPipelinePanel({ pipeline }: { pipeline: PaperProcessingPipelineStatus | null }) {
  if (!pipeline) return null;
  return (
    <section className="panel article-section processing-pipeline-panel">
      <div className="article-section-head">
        <div>
          <h2 className="article-section-title">Модель обработки AI/PDF/Qwen</h2>
          <p className="muted" style={{ marginTop: 4 }}>
            Итоговый статус документа отделён от отдельных этапов: пропуск, ошибка и fallback больше не смешиваются в одну строку.
          </p>
        </div>
        <span className={`status-pill status-pill-${pipelineTone(pipeline.aggregateStatus)}`}>
          {pipeline.aggregateLabel} · {pipeline.aggregateProgress}%
        </span>
      </div>
      <div className="processing-stage-grid">
        {pipeline.stages.map((stage) => (
          <div key={stage.key} className={`processing-stage-card processing-stage-${stage.status}`}>
            <div className="processing-stage-head">
              <strong>{stage.label}</strong>
              <span className={`status-pill status-pill-${pipelineTone(stage.status)}`}>{stage.statusLabel}</span>
            </div>
            <div className="paper-progress-track" role="progressbar" aria-label={stage.label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={stage.progress}>
              <div className={`paper-progress-fill ${stage.status === "error" ? "failed" : stage.progress >= 100 ? "done" : ""}`} style={{ width: `${Math.max(3, stage.progress)}%` }} />
            </div>
            <div className="processing-stage-meta">
              {stage.skipped && <span>пропущено</span>}
              {stage.fallbackUsed && <span>fallback</span>}
              {stage.error && <span title={stage.error}>ошибка: {stage.error}</span>}
              {!stage.skipped && !stage.fallbackUsed && !stage.error && <span>источник: {stage.source}</span>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}


function MarkdownText({ text }: { text: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
        skipHtml
      >
        {normalizeMarkdownForDisplay(text)}
      </ReactMarkdown>
    </div>
  );
}

function truncateForPreview(text: string, maxChars: number): string {
  const value = text || "";
  if (value.length <= maxChars) return value;
  return `${value.slice(0, maxChars).trimEnd()}\n\n…`;
}


function PartExtractionInfo({ part, compact = false }: { part: DisplayPart; compact?: boolean }) {
  const quality = formatQuality(part.extractionQualityScore);
  const method = methodLabel(part.extractionMethod);
  const contentType = contentTypeLabel(part.contentType);
  const warnings = part.extractionWarnings || [];
  const hasInfo = quality || method || contentType || part.pageProfile || warnings.length || part.error;
  if (!hasInfo) return null;

  return (
    <div className={`part-extraction-info${compact ? " compact" : ""}`}>
      <div className="part-extraction-info-main">
        {quality && <span>целостность {quality}</span>}
        {method && <span>метод: {method}</span>}
        {contentType && <span>тип: {contentType}</span>}
        {part.pageProfile && <span>профиль: {part.pageProfile}</span>}
        {part.error && <span>замечание: {part.error}</span>}
      </div>
      {warnings.length > 0 && (
        <div className="part-warning-list">
          {warnings.map((warning) => (
            <span key={warning} className="part-warning-chip">{warningLabel(warning)}</span>
          ))}
        </div>
      )}
    </div>
  );
}

type PlainTextBlock = {
  type: "paragraph" | "heading";
  text: string;
};


function looksLikeRawHeading(line: string): boolean {
  const value = line.trim();
  if (!value || value.length > 120) return false;
  if (/\.$/.test(value)) return false;
  return (
    /^(abstract|keywords|introduction|conclusion|references|acknowledg(e)?ments)$/i.test(value) ||
    /^([IVX]+|\d+(\.\d+)*)[.)]?\s+[A-ZА-ЯЁ]/.test(value) ||
    (value === value.toUpperCase() && /[A-ZА-ЯЁ]{3,}/.test(value))
  );
}

function joinTextLines(lines: string[]): string {
  return lines
    .map((line) => line.trim())
    .filter(Boolean)
    .reduce((acc, line) => {
      if (!acc) return line;
      if (/[-‐‑‒–—]$/.test(acc)) return acc.replace(/[-‐‑‒–—]$/, "") + line;
      return `${acc} ${line}`;
    }, "");
}

function stripPlainTextTechnicalMarker(line: string): string {
  return line
    .replace(/^\[(?:Formula|Table) candidate[^\]]*\]\s*/i, "")
    .replace(/^\[(?:Page|Страница)\s+\d+[^\]]*\]\s*/i, "")
    .trim();
}

function parsePlainTextForReading(text: string): PlainTextBlock[] {
  const rawLines = (text || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n");

  const blocks: PlainTextBlock[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const normalized = joinTextLines(paragraph);
    if (normalized) blocks.push({ type: "paragraph", text: normalized });
    paragraph = [];
  };

  for (const rawLine of rawLines) {
    const line = stripPlainTextTechnicalMarker(rawLine);

    if (!line) {
      flushParagraph();
      continue;
    }

    if (looksLikeRawHeading(line)) {
      flushParagraph();
      blocks.push({ type: "heading", text: line });
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  return blocks;
}

function extractApiErrorMessage(error: any): string {
  const data = error?.response?.data;
  if (data?.detail) return String(data.detail);
  if (data?.message) return String(data.message);
  return error?.message || "unknown error";
}

function ReportScoreCard({ title, value }: { title: string; value: number }) {
  const score = Math.max(0, Math.min(100, Math.round(Number(value || 0))));
  return (
    <article className="panel kpi-card article-report-score-card">
      <h3>{title}</h3>
      <p className={`kpi ${score >= 70 ? "ok" : score >= 40 ? "" : "idle"}`}>{score}%</p>
    </article>
  );
}

function RegenerationModeSelect({
  value,
  onChange,
  disabled = false,
  id,
}: {
  value: PaperRegenerationMode;
  onChange: (value: PaperRegenerationMode) => void;
  disabled?: boolean;
  id: string;
}) {
  return (
    <label className="regeneration-mode-select" htmlFor={id}>
      <span>{RU.regenerateMode}</span>
      <select
        id={id}
        className="input"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as PaperRegenerationMode)}
      >
        <option value="text" title={RU.regenerateModeTextHint}>{RU.regenerateModeText}</option>
        <option value="image" title={RU.regenerateModeImageHint}>{RU.regenerateModeImage}</option>
      </select>
    </label>
  );
}

function PdfProcessingModeSelect({
  value,
  onChange,
  disabled = false,
  id,
}: {
  value: PdfProcessingMode;
  onChange: (value: PdfProcessingMode) => void;
  disabled?: boolean;
  id: string;
}) {
  return (
    <label className="regeneration-mode-select" htmlFor={id}>
      <span>{RU.pdfMode}</span>
      <select
        id={id}
        className="input"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as PdfProcessingMode)}
      >
        <option value="auto" title={RU.pdfModeAutoHint}>{RU.pdfModeAuto}</option>
        <option value="mypdf" title={RU.pdfModeMypdfHint}>{RU.pdfModeMypdf}</option>
        <option value="ai" title={RU.pdfModeAiHint}>{RU.pdfModeAi}</option>
      </select>
    </label>
  );
}

function PlainTextDocument({ text }: { text: string }) {
  const blocks = parsePlainTextForReading(text);

  if (!blocks.length) return <p className="muted">{RU.emptyText}</p>;

  return (
    <div className="plain-document-body">
      {blocks.map((block, index) => (
        block.type === "heading"
          ? <h4 className="plain-document-heading" key={index}>{block.text}</h4>
          : <p className="plain-document-paragraph" key={index}>{block.text}</p>
      ))}
    </div>
  );
}

export default function PatentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const isAdmin = !!useAuthStore((s) => s.user?.is_admin);

  const [paper, setPaper] = useState<Paper | null>(null);
  const [paperStatusInfo, setPaperStatusInfo] = useState<PaperProcessingStatusInfo | null>(null);
  const [processingQuality, setProcessingQuality] = useState<PaperProcessingQualityInfo | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PaperProcessingPipelineStatus | null>(null);
  const [contentParts, setContentParts] = useState<PaperContentPart[]>([]);
  const [contentPartsError, setContentPartsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pollingWarning, setPollingWarning] = useState<string | null>(null);
  const [pdfObjectUrl, setPdfObjectUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfPreviewRequested, setPdfPreviewRequested] = useState(false);
  const [tab, setTab] = useState<Tab>("main");
  const [activePartIndex, setActivePartIndex] = useState(0);
  const [textViewMode, setTextViewMode] = useState<TextViewMode>("ai");
  const [showExtractionDiagnostics, setShowExtractionDiagnostics] = useState(true);
  const [actionBusy, setActionBusy] = useState<BusyAction>(null);
  const [regeneratingPartKey, setRegeneratingPartKey] = useState<string | null>(null);
  const [partRegenerationMode, setPartRegenerationMode] = useState<PaperRegenerationMode>("text");
  const [selectedTextLanguage, setSelectedTextLanguage] = useState("original");
  const [textLanguageTouched, setTextLanguageTouched] = useState(false);
  const [translationTargetLanguage, setTranslationTargetLanguage] = useState("ru");
  const [translationForce, setTranslationForce] = useState(false);
  const [translatingText, setTranslatingText] = useState(false);
  const [documentPdfMode, setDocumentPdfMode] = useState<PdfProcessingMode>("auto");
  const [report, setReport] = useState<PaperReportData | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportWarning, setReportWarning] = useState<string | null>(null);
  const [exportingReport, setExportingReport] = useState<ReportExportFormat | null>(null);

  const loadPaper = async (showLoading = true) => {
    const paperId = Number(id);
    if (!paperId || Number.isNaN(paperId)) {
      setLoadError(RU.invalidId);
      setLoading(false);
      return;
    }

    if (showLoading) setLoading(true);
    if (showLoading) setLoadError(null);

    try {
      const details = await getPaperDetails(paperId);
      setPaper(details.paper);
      setPaperStatusInfo(details.statusInfo ?? null);
      setProcessingQuality(details.processingQuality ?? null);
      setPipelineStatus(details.pipelineStatus ?? null);
      setContentParts(details.contentParts);
      setContentPartsError(null);
      setLoadError(null);
      setPollingWarning(null);
    } catch (e) {
      const message = (e as Error).message;
      if (showLoading || !paper) setLoadError(message);
      else setPollingWarning(`Не удалось обновить статус статьи: ${message}`);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    setReport(null);
    setReportWarning(null);
    setActivePartIndex(0);
    setTextLanguageTouched(false);
    setPdfPreviewRequested(false);
    loadPaper();
    getPublicDisplaySettings()
      .then((value) => setShowExtractionDiagnostics(value.show_extraction_diagnostics ?? true))
      .catch(() => setShowExtractionDiagnostics(true));
  }, [id]);

  useEffect(() => {
    if (!paper) return;
    const processing = paperStatusInfo ? !paperStatusInfo.final : isPaperProcessing(paper.processingStatus);
    const translationProcessing = paper.translationStatus?.startsWith("translating_article");
    if (!processing && !translationProcessing) return;
    const timer = window.setInterval(() => {
      loadPaper(false).catch(() => null);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [paper?.id, paper?.processingStatus, paper?.translationStatus, paperStatusInfo?.final]);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;

    if (!paper?.id || !(paper.pdfUrl || paper.pdfLocalPath) || !pdfPreviewRequested) {
      setPdfObjectUrl(null);
      setPdfLoading(false);
      setPdfError(null);
      return () => undefined;
    }

    if (!paper.pdfLocalPath) {
      setPdfObjectUrl(null);
      setPdfLoading(false);
      setPdfError(RU.pdfNotCached);
      return () => undefined;
    }

    setPdfObjectUrl(null);
    setPdfLoading(true);
    setPdfError(null);

    getPaperPdfBlobUrl(paper.id)
      .then((url) => {
        objectUrl = url;
        if (active) setPdfObjectUrl(url);
        else URL.revokeObjectURL(url);
      })
      .catch((e) => {
        if (!active) return;
        setPdfError((e as Error).message || RU.pdfLoadError);
      })
      .finally(() => {
        if (active) setPdfLoading(false);
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [paper?.id, paper?.pdfUrl, paper?.pdfLocalPath, pdfPreviewRequested]);

  const onTranslateArticleText = async () => {
    if (!paper) return;
    setTranslatingText(true);
    setActionError(null);
    try {
      const targetLabel = languageLabel(translationTargetLanguage, paper);
      await translatePaperText(paper.id, {
        targetLanguageCode: translationTargetLanguage,
        targetLanguageName: targetLabel,
        force: translationForce,
      });
      toast.success(RU.translationQueued);
      setTextLanguageTouched(true);
      setSelectedTextLanguage(translationTargetLanguage);
      await loadPaper(false);
    } catch (e) {
      const message = (e as Error).message || RU.translationError;
      setActionError(message);
      toast.error(`${RU.translationError}: ${message}`);
    } finally {
      setTranslatingText(false);
    }
  };

  const fullText = paper?.fullText ?? "";
  const hasFullText = Boolean(fullText.trim().length);
  const hasPdf = Boolean(paper?.pdfUrl || paper?.pdfLocalPath);
  const hasLocalPdf = Boolean(paper?.pdfLocalPath);
  const localPdfHref = paper?.id && hasLocalPdf ? getPaperPdfUrl(paper.id) : null;
  const provenanceEntries = nonEmptyEntries(paper?.provenance);
  const rawPartsChars = contentParts.reduce((sum, part) => sum + Number(part.rawTextChars || part.rawText?.length || 0), 0);
  const markdownPartsChars = contentParts.reduce((sum, part) => sum + Number(part.markdownTextChars || part.markdownText?.length || 0), 0);
  const embeddingPartsCount = contentParts.filter((part) => part.includeInEmbedding).length;
  const localPaperStatusLabel = getProcessingStatusLabel(paper?.processingStatus);
  const paperStatusLabel = paper?.processingStatus?.startsWith("digitizing_file:")
    ? localPaperStatusLabel
    : paperStatusInfo?.label || localPaperStatusLabel;
  const paperStatusProgress = paperStatusInfo?.final ? 100 : getProcessingProgress(paper?.processingStatus);
  const fileQuality = fileProcessingQualitySummary(contentParts, processingQuality);

  const legacyMarkdownParts = useMemo<DisplayPart[]>(() => splitLegacyMarkdownParts(fullText), [fullText]);

  const displayParts = useMemo<DisplayPart[]>(() => {
    if (!contentParts.length) return legacyMarkdownParts;

    const storedParts = aggregateStoredPartsByPage(contentParts, legacyMarkdownParts);
    const hasAnyAiMarkdown = storedParts.some((part) => part.markdown.trim().length > 0);
    const hasAnyTranslationLayer = storedParts.some((part) =>
      part.translations.some((translation) => translation.text?.trim() || translation.status === "processing"),
    );

    // Если backend уже собрал Markdown в paper.full_text, но отдельные content_parts
    // ещё не содержат markdown_text, не показываем ложное «Текст после ИИ ещё не готов».
    // Но если у сохранённых частей уже есть переводы, оставляем storedParts: иначе языковой
    // слой будет существовать в БД, но UI переключится на legacy-блоки без translations.
    if (!hasAnyAiMarkdown && legacyMarkdownParts.length && !hasAnyTranslationLayer) return legacyMarkdownParts;

    return storedParts;
  }, [contentParts, legacyMarkdownParts]);

  const displayedAiChars = displayParts.reduce((sum, part) => sum + (part.markdownTextChars || part.markdown.length || 0), 0);
  const mainPreviewParts = displayParts;
  const originalLanguageCode = (paper?.languageCode || "original").trim().toLowerCase() || "original";
  const availableTextLanguages = useMemo(() => {
    const map = new Map<string, string>();
    map.set("original", `${RU.originalTextLanguage}${paper && (paper.languageName || paper.languageCode) ? ` · ${formatPaperLanguage(paper)}` : ""}`);
    for (const code of paper?.availableLanguageCodes ?? []) {
      const normalized = (code || "").trim().toLowerCase();
      if (!normalized || normalized === originalLanguageCode) continue;
      map.set(normalized, languageLabel(normalized, paper));
    }
    for (const part of displayParts) {
      for (const translation of part.translations) {
        if (!translation.text?.trim() && translation.status !== "processing") continue;
        map.set(translation.languageCode, languageLabel(translation.languageCode, paper, translation.languageName));
      }
    }
    return Array.from(map.entries()).map(([code, label]) => ({ code, label }));
  }, [displayParts, originalLanguageCode, paper]);
  const hasSelectedTranslation = selectedTextLanguage !== "original";
  const translationInProgress = Boolean(paper?.translationStatus?.startsWith("translating_article"));
  const hasTranslatableMarkdown = displayParts.some((part) => part.markdown.trim().length > 0);
  const fallbackFullTextPreview = paper?.fullText ?? "";
  const selectedPart = displayParts[activePartIndex] ?? null;

  useEffect(() => {
    if (tab === "parts" && !hasFullText && !displayParts.length) setTab("main");
  }, [tab, hasFullText, displayParts.length]);

  useEffect(() => {
    if (activePartIndex >= displayParts.length) setActivePartIndex(0);
  }, [activePartIndex, displayParts.length]);

  useEffect(() => {
    const codes = availableTextLanguages.map((item) => item.code);
    if (!codes.includes(selectedTextLanguage)) {
      setSelectedTextLanguage(codes.includes("ru") ? "ru" : "original");
      return;
    }
    if (!textLanguageTouched && selectedTextLanguage === "original" && codes.includes("ru")) {
      setSelectedTextLanguage("ru");
    }
  }, [availableTextLanguages, selectedTextLanguage, textLanguageTouched]);

  const activeLayerStatus = useMemo(() => {
    if (textViewMode === "raw") return getRawPartStatus(selectedPart);
    if (hasSelectedTranslation) return getTranslationPartStatus(selectedPart, selectedTextLanguage);
    return getAiPartStatus(selectedPart);
  }, [hasSelectedTranslation, selectedPart, selectedTextLanguage, textViewMode]);

  const rawOverallStatus = useMemo(() => getOverallLayerStatus(displayParts, "raw"), [displayParts]);
  const aiOverallStatus = useMemo(() => getOverallLayerStatus(displayParts, "ai"), [displayParts]);
  const translationOverallStatus = useMemo(
    () => getOverallTranslationStatus(displayParts, selectedTextLanguage),
    [displayParts, selectedTextLanguage],
  );
  const selectedTextOverallStatus = textViewMode === "raw"
    ? rawOverallStatus
    : hasSelectedTranslation
      ? translationOverallStatus
      : aiOverallStatus;
  const selectedTranslationSummary = useMemo(
    () => getTranslationSummary(displayParts, selectedTextLanguage),
    [displayParts, selectedTextLanguage],
  );
  const targetSameAsOriginal = translationTargetLanguage.trim().toLowerCase() === originalLanguageCode && originalLanguageCode !== "original";
  const canTranslateArticle = hasTranslatableMarkdown && !targetSameAsOriginal;



  const onDelete = async () => {
    if (!isAdmin) return;
    if (!paper || actionBusy) return;
    if (!window.confirm(RU.confirmDelete)) return;
    setActionBusy("delete");
    setActionError(null);
    try {
      await deletePaper(paper.id);
      toast.success(RU.deleteOk);
      navigate("/papers");
    } catch (e) {
      const message = (e as Error).message;
      setActionError(`${RU.deleteError}: ${message}`);
      toast.error(`${RU.deleteError}: ${message}`);
    } finally {
      setActionBusy(null);
    }
  };

  const onReprocess = async () => {
    if (!isAdmin) return;
    if (!paper || actionBusy) return;
    setActionBusy("reprocess");
    setActionError(null);
    try {
      await reprocessPaperContent(paper.id, documentPdfMode);
      toast.success(RU.reprocessQueued);
      await loadPaper(false);
    } catch (e) {
      const message = (e as Error).message;
      setActionError(`${RU.reprocessError}: ${message}`);
      toast.error(`${RU.reprocessError}: ${message}`);
    } finally {
      setActionBusy(null);
    }
  };

  const onRegeneratePart = async (part: DisplayPart, mode: PaperRegenerationMode = partRegenerationMode) => {
    if (!isAdmin) {
      toast.error(RU.adminOnlyRegenerate);
      return;
    }
    const key = getRegenerationKey(part);
    if (!paper || !key || regeneratingPartKey) return;
    setRegeneratingPartKey(key);
    setActionError(null);
    try {
      const sourcePartIds = Array.from(new Set(part.sourcePartIds.filter((partId) => Number.isFinite(partId))));
      if (sourcePartIds.length > 1) {
        await Promise.all(sourcePartIds.map((partId) => regeneratePaperContentPart(paper.id, partId, mode)));
      } else if (part.id) {
        await regeneratePaperContentPart(paper.id, part.id, mode);
      } else if (part.pageStart && part.pageEnd) {
        await regeneratePaperMarkdownPages(paper.id, part.pageStart, part.pageEnd, mode);
      }
      toast.success(RU.regenerateQueued);
      await loadPaper(false);
    } catch (e) {
      const message = (e as Error).message;
      setActionError(`${RU.regenerateError}: ${message}`);
      toast.error(`${RU.regenerateError}: ${message}`);
    } finally {
      setRegeneratingPartKey(null);
    }
  };

  const copyGist = async () => {
    if (!paper?.summaryRu?.trim()) {
      toast.warning(RU.copyEmpty);
      return;
    }
    try {
      await navigator.clipboard.writeText(paper.summaryRu);
      toast.success(RU.copied);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const loadReport = async () => {
    if (!paper?.id || reportLoading) return;
    setReportLoading(true);
    setReportWarning(null);
    try {
      const nextReport = await getPaperReport(paper.id);
      setReport(nextReport);
    } catch (e) {
      setReport(null);
      setReportWarning(`${RU.reportLoadError} Подробности: ${(e as Error).message}`);
    } finally {
      setReportLoading(false);
    }
  };

  const onExportReport = async (format: ReportExportFormat) => {
    if (!paper?.id || exportingReport) return;
    setExportingReport(format);
    setActionError(null);
    try {
      const blob = await exportPaperReport(paper.id, format);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `paper_${paper.id}_report.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      const message = extractApiErrorMessage(e);
      setActionError(`${format === "pdf" ? RU.exportPdf : RU.exportDocx}: ${message}`);
    } finally {
      setExportingReport(null);
    }
  };

  useEffect(() => {
    if (tab === "report" && paper?.id && !report && !reportLoading && !reportWarning) {
      loadReport().catch(() => null);
    }
  }, [tab, paper?.id, report, reportLoading, reportWarning]);

  if (loading) return <p className="muted">{RU.loading}</p>;
  if (loadError && !paper) return <p className="error">{loadError}</p>;
  if (!paper) return <p className="muted">{RU.notFound}</p>;

  return (
    <div className="page article-detail-page">
      <p className="muted">
        <Link to="/dashboard">{RU.home}</Link> → <Link to="/papers">{RU.papers}</Link> → {paper.title}
      </p>

      {actionError && <p className="error">{actionError}</p>}
      {pollingWarning && <p className="muted">{pollingWarning}</p>}
      {contentPartsError && <p className="muted">{RU.contentPartsLoadError} Подробности: {contentPartsError}</p>}

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>{paper.title}</h2>
        <div className="detail-grid">
          <p><strong>{RU.authors}:</strong> {paper.authors.length ? paper.authors.join(", ") : RU.unknown}</p>
          <p><strong>{RU.source}:</strong> {paper.source}</p>
          <p><strong>{RU.date}:</strong> {paper.publicationDate ? paper.publicationDate.slice(0, 10) : RU.unknown}</p>
          <p><strong>{RU.journal}:</strong> {paper.journal ?? RU.unknown}</p>
          <p><strong>DOI:</strong> {paper.doi ?? RU.unknown}</p>
          <p><strong>{RU.keywords}:</strong> {paper.keywords.length ? paper.keywords.join(", ") : RU.unknown}</p>
          <p><strong>{RU.language}:</strong> {formatPaperLanguage(paper)}</p>
          <div className="detail-progress">
            <div className="paper-progress-head">
              <strong>{RU.status}:</strong>
              <span>{paperStatusLabel} - {paperStatusProgress}%</span>
            </div>
            <div
              className="paper-progress-track"
              role="progressbar"
              aria-label={`Прогресс обработки статьи ${paper.id}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={paperStatusProgress}
            >
              <div
                className={`paper-progress-fill ${paperStatusInfo?.group === "error" || paper.processingStatus === "failed" ? "failed" : paperStatusProgress === 100 ? "done" : ""}`}
                style={{ width: `${Math.max(3, paperStatusProgress)}%` }}
              />
            </div>
          </div>
          {paper.translationStatus && (
            <p>
              <strong>{RU.translationStatus}:</strong> {getProcessingStatusLabel(paper.translationStatus)}
              {paper.translationError ? ` · ${paper.translationError}` : ""}
            </p>
          )}
          <p><strong>{RU.fullText}:</strong> {hasFullText ? RU.yes : RU.no}</p>
          <p><strong>URL:</strong> {paper.url ? <a href={paper.url} target="_blank" rel="noreferrer" className="action-link">{RU.open}</a> : RU.unknown}</p>
          <p>
            <strong>PDF:</strong>{" "}
            {hasPdf ? (
              localPdfHref ? (
                <a href={localPdfHref} download className="action-link">Скачать PDF</a>
              ) : paper.pdfUrl ? (
                <a href={paper.pdfUrl} target="_blank" rel="noreferrer" className="action-link">Скачать PDF</a>
              ) : (
                RU.unknown
              )
            ) : RU.unknown}
          </p>
          <p><strong>{RU.workerTask}:</strong> {paper.contentTaskId ?? RU.unknown}</p>
        </div>
      </div>

      {paper.abstract?.trim() && (
        <section className="panel article-section article-abstract-panel">
          <h2 className="article-section-title">{RU.abstract}</h2>
          <p className="article-abstract-text">{paper.abstract}</p>
        </section>
      )}

      <ProcessingPipelinePanel pipeline={pipelineStatus} />

      <details className="panel article-section article-data-details">
        <summary className="article-data-summary">
          <span>{RU.allArticleData}</span>
          <small>{RU.allArticleDataHint}</small>
        </summary>
        <FieldList
          rows={[
            [RU.status, paperStatusLabel],
            [RU.sourceId, paper.sourceId ?? RU.unknown],
            [RU.canonicalPatentId, <FieldValueWithHint value={paper.canonicalPatentId ?? RU.unknown} hint={RU.canonicalPatentIdHint} />],
            [RU.pdfUrl, paper.pdfUrl ? <a href={paper.pdfUrl} target="_blank" rel="noreferrer" className="action-link">{paper.pdfUrl}</a> : RU.unknown],
            [RU.pdfLocalPath, paper.pdfLocalPath ? "Есть" : "Нет"],
            [RU.createdAt, formatDateTime(paper.createdAt)],
            [RU.updatedAt, formatDateTime(paper.updatedAt)],
            [RU.fileProcessingQuality, <FieldValueWithHint value={fileQuality.value} hint={fileQuality.hint} />],
            [RU.metadataParseConfidence, <FieldValueWithHint value={formatPercent(paper.parseConfidence)} hint={RU.metadataParseConfidenceHint} />],
            [RU.language, formatPaperLanguage(paper)],
            ["Код языка", paper.languageCode ?? RU.unknown],
            ["Источник языка", paper.languageSource ?? RU.unknown],
            [RU.schemaVersion, paper.schemaVersion ?? RU.unknown],
            [RU.contentPartsCount, String(contentParts.length)],
            [RU.rawChars, String(rawPartsChars)],
            [RU.aiChars, String(displayedAiChars || markdownPartsChars)],
            [RU.embeddingParts, String(embeddingPartsCount)],
          ]}
        />

        <div style={{ marginTop: 12 }}>
          <h3 style={{ marginBottom: 8 }}>{RU.qualityFlags}</h3>
          <p className="quality-flags-hint">{RU.qualityFlagsHint}</p>
          {paper.qualityFlags.length ? (
            <div className="part-warning-list">
              {paper.qualityFlags.map((flag) => <span key={flag} className="part-warning-chip" title={qualityFlagHint(flag)}>{qualityFlagLabel(flag)}</span>)}
            </div>
          ) : (
            <p className="muted">{RU.noQualityFlags}</p>
          )}
        </div>

        <div style={{ marginTop: 12 }}>
          <h3 style={{ marginBottom: 8 }}>{RU.provenance}</h3>
          {provenanceEntries.length ? (
            <div className="detail-grid">
              {provenanceEntries.map(([key, value]) => (
                <p key={key}><strong>{key}:</strong> {value}</p>
              ))}
            </div>
          ) : (
            <p className="muted">{RU.noProvenance}</p>
          )}
        </div>
      </details>

      <div className="tabs">
        <button className={`btn ${tab === "main" ? "btn-primary" : ""}`} onClick={() => setTab("main")}>{RU.tabMain}</button>
        {(hasFullText || displayParts.length > 0) && (
          <button className={`btn ${tab === "parts" ? "btn-primary" : ""}`} onClick={() => setTab("parts")}>{RU.tabParts}</button>
        )}
        <button className={`btn ${tab === "report" ? "btn-primary" : ""}`} onClick={() => setTab("report")}>{RU.tabReport}</button>
      </div>

      {tab === "main" && (
        <article className="panel article-main-panel">
          <section className="article-section article-summary-section">
            <h2 className="article-section-title">{RU.gist}</h2>
            {paper.summaryRu ? (
              <p className="article-summary-text">{paper.summaryRu}</p>
            ) : (
              <p className="article-summary-placeholder">{RU.gistNotReady}</p>
            )}
          </section>


          {hasPdf && (
            <section className="article-section article-pdf-section">
              <h2 className="article-section-title">{RU.pdfLen}</h2>
              {localPdfHref ? (
                pdfPreviewRequested ? (
                  <div className="article-pdf-preview-panel">
                    <div className="article-pdf-preview-actions">
                      <a href={localPdfHref} download className="btn">Скачать PDF</a>
                    </div>
                    {pdfLoading && <p className="muted">{RU.pdfLoading}</p>}
                    {pdfError && <p className="error">{RU.pdfLoadError}: {pdfError}</p>}
                    {pdfObjectUrl && (
                      <iframe
                        className="article-pdf-frame"
                        src={pdfObjectUrl}
                        title={`PDF: ${paper.title}`}
                      />
                    )}
                  </div>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary article-pdf-direct-link"
                    onClick={() => setPdfPreviewRequested(true)}
                  >
                    Открыть просмотр PDF
                  </button>
                )
              ) : paper.pdfUrl ? (
                <a href={paper.pdfUrl} target="_blank" rel="noreferrer" className="btn article-pdf-direct-link">
                  {RU.openPdf}
                </a>
              ) : (
                <div>
                  <p className="muted">{RU.pdfNotCached}</p>
                  {isAdmin && (
                    <div className="regeneration-controls">
                      <PdfProcessingModeSelect
                        id="document-pdf-mode-inline"
                        value={documentPdfMode}
                        onChange={setDocumentPdfMode}
                        disabled={actionBusy === "reprocess"}
                      />
                      <button className="btn" onClick={onReprocess} disabled={actionBusy === "reprocess"}>
                        {actionBusy === "reprocess" ? RU.actionInProgress : RU.queuePdfProcessing}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          {(paper.fullText || displayParts.length > 0) && (
            <section className="article-section article-text-section">
              <div className="article-section-head">
                <h2 className="article-section-title">{RU.articleText}</h2>
                <StatusPill status={selectedTextOverallStatus} />
              </div>

              {displayParts.length ? (
                <>
                  <div className="article-text-tabs" role="tablist" aria-label={RU.articleText}>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={textViewMode === "raw"}
                      className={`article-text-tab ${textViewMode === "raw" ? "active" : ""}`}
                      onClick={() => setTextViewMode("raw")}
                    >
                      {RU.textFromFile}
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={textViewMode === "ai"}
                      className={`article-text-tab ${textViewMode === "ai" ? "active" : ""}`}
                      onClick={() => setTextViewMode("ai")}
                    >
                      {RU.textAfterAi}
                    </button>
                  </div>

                  {textViewMode === "ai" && (
                    <div className="article-translation-toolbar">
                      <label className="article-language-select">
                        <span>{RU.textLanguage}</span>
                        <select
                          className="input"
                          value={selectedTextLanguage}
                          onChange={(event) => { setTextLanguageTouched(true); setSelectedTextLanguage(event.target.value); }}
                        >
                          {availableTextLanguages.map((item) => (
                            <option key={item.code} value={item.code}>{item.label}</option>
                          ))}
                        </select>
                      </label>
                      {hasSelectedTranslation && (
                        <div className={`article-translation-summary status-pill-${translationOverallStatus.tone}`}>
                          {languageLabel(selectedTextLanguage, paper)}: {formatTranslationSummary(selectedTranslationSummary)}
                        </div>
                      )}
                      {paper?.translationStatus && (
                        <div className="article-translation-summary muted">
                          {RU.translationStatus}: {getProcessingStatusLabel(paper.translationStatus)}
                          {paper.translationError ? ` · ${paper.translationError}` : ""}
                        </div>
                      )}
                      {isAdmin && (
                        <div className="article-translate-actions">
                          <label className="article-language-select">
                            <span>{RU.translateTarget}</span>
                            <select
                              className="input"
                              value={translationTargetLanguage}
                              onChange={(event) => setTranslationTargetLanguage(event.target.value)}
                              disabled={translatingText || translationInProgress}
                            >
                              <option value="ru">Русский</option>
                              <option value="en">English</option>
                              <option value="de">Deutsch</option>
                              <option value="fr">Français</option>
                              <option value="es">Español</option>
                              <option value="zh">中文</option>
                            </select>
                          </label>
                          <label className="article-translation-force">
                            <input
                              type="checkbox"
                              checked={translationForce}
                              onChange={(event) => setTranslationForce(event.target.checked)}
                              disabled={translatingText || translationInProgress}
                            />
                            <span title={RU.translationForceHint}>{RU.translationForce}</span>
                          </label>
                          <button
                            type="button"
                            className="btn btn-primary"
                            onClick={onTranslateArticleText}
                            disabled={translatingText || translationInProgress || !canTranslateArticle}
                            title={!hasTranslatableMarkdown ? "Нет Markdown-текста после ИИ для перевода" : targetSameAsOriginal ? RU.translationSameLanguage : undefined}
                          >
                            {translatingText || translationInProgress ? RU.translatingArticleText : RU.translateArticleText}
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {textViewMode === "raw" && showExtractionDiagnostics && rawOverallStatus.detail && (
                    <p className="article-text-integrity">{rawOverallStatus.detail}</p>
                  )}

                  <div className="article-text-scroll-panel">
                    <div className="markdown-parts-readable">
                      {mainPreviewParts.map((part, idx) => {
                        const rawStatus = getRawPartStatus(part);
                        const aiStatus = getAiPartStatus(part);
                        const translationStatus = hasSelectedTranslation ? getTranslationPartStatus(part, selectedTextLanguage) : aiStatus;
                        const translation = hasSelectedTranslation ? getPartTranslation(part, selectedTextLanguage) : null;
                        const text = textViewMode === "raw" ? part.rawText || "" : hasSelectedTranslation ? translation?.text || "" : part.markdown || "";
                        return (
                          <section className="markdown-part-readonly" key={`${part.id ?? "legacy"}-${idx}`}>
                            <div className="markdown-part-header compact">
                              <div>
                                <h4>{part.title}</h4>
                                <div className="part-status-row compact-row">
                                  <StatusPill status={textViewMode === "raw" ? rawStatus : translationStatus} />
                                </div>
                                {textViewMode === "raw" && showExtractionDiagnostics && (
                                  <PartExtractionInfo part={part} compact />
                                )}
                              </div>
                              {isAdmin && textViewMode === "ai" && (
                                <div className="regeneration-controls compact">
                                  <RegenerationModeSelect
                                    id={`readonly-regeneration-mode-${part.id ?? idx}`}
                                    value={partRegenerationMode}
                                    onChange={setPartRegenerationMode}
                                    disabled={regeneratingPartKey === getRegenerationKey(part)}
                                  />
                                  <button
                                    className="btn btn-primary"
                                    disabled={!getRegenerationKey(part) || regeneratingPartKey === getRegenerationKey(part)}
                                    onClick={() => onRegeneratePart(part, partRegenerationMode)}
                                    title={!getRegenerationKey(part) ? "Перегенерация доступна только для сохранённых страниц" : undefined}
                                  >
                                    {regeneratingPartKey === getRegenerationKey(part) ? RU.regenerating : RU.regenerate}
                                  </button>
                                </div>
                              )}
                            </div>
                            {textViewMode === "raw" ? (
                              text.trim() ? <PlainTextDocument text={text} /> : <p className="muted">{RU.rawNotAvailable}</p>
                            ) : (
                              text.trim() ? (
                                <MarkdownText text={text} />
                              ) : hasSelectedTranslation && translation?.status === "processing" ? (
                                <p className="muted">{RU.translationPending}</p>
                              ) : hasSelectedTranslation ? (
                                <p className="muted">{translation?.error || RU.translationMissing}</p>
                              ) : (
                                <p className="muted">{RU.aiNotAvailable}</p>
                              )
                            )}
                          </section>
                        );
                      })}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <MarkdownText text={fallbackFullTextPreview} />

                </>
              )}
            </section>
          )}


          <div className="article-actions-row">
            {isAdmin && (
              <div className="regeneration-controls">
                <PdfProcessingModeSelect
                  id="document-pdf-mode-main"
                  value={documentPdfMode}
                  onChange={setDocumentPdfMode}
                  disabled={actionBusy === "reprocess"}
                />
                <button className="btn" onClick={onReprocess} disabled={actionBusy === "reprocess"}>
                  {actionBusy === "reprocess" ? RU.actionInProgress : RU.reprocessBtn}
                </button>
              </div>
            )}
          </div>
        </article>
      )}

      {tab === "parts" && (
        <article className="panel">
          {!contentParts.length && displayParts.length > 0 && <p className="muted">{RU.noStoredParts}</p>}
          <div className="markdown-parts-layout">
            <div className="panel markdown-parts-sidebar">
              <h3 style={{ marginTop: 0 }}>{RU.parts}</h3>
              {!displayParts.length ? <p className="muted">{RU.emptyText}</p> : (
                <div className="markdown-parts-list">
                  {displayParts.map((part, idx) => (
                    <button
                      key={`${part.id ?? "legacy"}-${idx}`}
                      className={`btn markdown-part-nav ${idx === activePartIndex ? "btn-primary" : ""}`}
                      onClick={() => setActivePartIndex(idx)}
                    >
                      <span>{part.title}</span>
                      <small>{textViewMode === "raw" ? getRawPartStatus(part).label : getAiPartStatus(part).label}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="panel markdown-part-card">
              {selectedPart ? (
                <>
                  <div className="markdown-part-header">
                    <div>
                      <h3 style={{ margin: 0 }}>{selectedPart.title}</h3>
                      <div className="part-status-row" style={{ marginTop: 8 }}>
                        <StatusPill status={activeLayerStatus} />
                      </div>
                      <p className="muted" style={{ margin: "6px 0 0" }}>
                        текст из файла: {selectedPart.rawTextChars || selectedPart.rawText?.length || 0} симв. · после ИИ: {selectedPart.markdownTextChars || selectedPart.markdown.length} симв.
                        {selectedPart.regenerationCount ? ` · регенераций: ${selectedPart.regenerationCount}` : ""}
                      </p>
                      {textViewMode === "raw" && showExtractionDiagnostics && (
                        <PartExtractionInfo part={selectedPart} />
                      )}
                    </div>
                    <div className="markdown-part-actions">
                      <button
                        className={`btn ${textViewMode === "raw" ? "btn-primary" : ""}`}
                        onClick={() => setTextViewMode("raw")}
                      >
                        {RU.textFromFile}
                      </button>
                      <button
                        className={`btn ${textViewMode === "ai" ? "btn-primary" : ""}`}
                        onClick={() => setTextViewMode("ai")}
                      >
                        {RU.textAfterAi}
                      </button>
                      {textViewMode === "ai" && (
                        <select
                          className="input markdown-part-language-select"
                          value={selectedTextLanguage}
                          onChange={(event) => { setTextLanguageTouched(true); setSelectedTextLanguage(event.target.value); }}
                          aria-label={RU.textLanguage}
                        >
                          {availableTextLanguages.map((item) => (
                            <option key={item.code} value={item.code}>{item.label}</option>
                          ))}
                        </select>
                      )}
                      {isAdmin && (
                        <div className="regeneration-controls compact">
                          <RegenerationModeSelect
                            id={`selected-regeneration-mode-${selectedPart.id ?? activePartIndex}`}
                            value={partRegenerationMode}
                            onChange={setPartRegenerationMode}
                            disabled={regeneratingPartKey === getRegenerationKey(selectedPart)}
                          />
                          <button
                            className="btn btn-primary"
                            disabled={!getRegenerationKey(selectedPart) || regeneratingPartKey === getRegenerationKey(selectedPart)}
                            onClick={() => onRegeneratePart(selectedPart, partRegenerationMode)}
                            title={!getRegenerationKey(selectedPart) ? "Перегенерация доступна только для сохранённых страниц" : undefined}
                          >
                            {regeneratingPartKey === getRegenerationKey(selectedPart) ? RU.regenerating : RU.regenerate}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {selectedPart.error && <p className="error">{selectedPart.error}</p>}

                  {textViewMode === "raw" && showExtractionDiagnostics && activeLayerStatus.detail && (
                    <div className="selected-layer-status">
                      <span className="muted">{activeLayerStatus.detail}</span>
                    </div>
                  )}

                  {textViewMode === "raw" ? (
                    selectedPart.rawText?.trim() ? <PlainTextDocument text={selectedPart.rawText} /> : <p className="muted">{RU.rawNotAvailable}</p>
                  ) : (() => {
                    const translation = hasSelectedTranslation ? getPartTranslation(selectedPart, selectedTextLanguage) : null;
                    const markdown = hasSelectedTranslation ? translation?.text || "" : selectedPart.markdown;
                    if (markdown.trim()) return <MarkdownText text={markdown} />;
                    if (hasSelectedTranslation && translation?.status === "processing") return <p className="muted">{RU.translationPending}</p>;
                    if (hasSelectedTranslation) return <p className="muted">{translation?.error || RU.translationMissing}</p>;
                    return <p className="muted">{RU.aiNotAvailable}</p>;
                  })()}
                </>
              ) : <p className="muted">{RU.emptyText}</p>}
            </div>
          </div>
        </article>
      )}

      {tab === "report" && (
        <article className="panel article-report-tab">
          <div className="article-section-head">
            <h2 className="article-section-title">{RU.reportTitle}</h2>
            <div className="actions">
              <button
                className="btn"
                onClick={() => void onExportReport("pdf")}
                disabled={exportingReport === "pdf"}
              >
                {exportingReport === "pdf" ? RU.exporting : RU.exportPdf}
              </button>
              <button
                className="btn"
                onClick={() => void onExportReport("docx")}
                disabled={exportingReport === "docx"}
              >
                {exportingReport === "docx" ? RU.exporting : RU.exportDocx}
              </button>
            </div>
          </div>

          {paper.processingError && <p className="error" style={{ marginTop: 12 }}>{RU.processingError}: {paper.processingError}</p>}
          {reportWarning && <p className="muted">{reportWarning}</p>}
          {reportLoading && <p className="muted">Загрузка отчёта...</p>}

          <div className="kpi-grid article-report-score-grid">
            <ReportScoreCard title="Оценка полноты отчёта" value={report?.scores?.quality_score ?? 0} />
            <ReportScoreCard title="Полнота" value={report?.scores?.completeness_score ?? 0} />
            <article className="panel kpi-card article-report-score-card">
              <h3>Аннотация</h3>
              <p className="kpi">{report?.abstract_length ?? (paper.abstract?.length || 0)}</p>
              <small>{RU.symbols}</small>
            </article>
            <article className="panel kpi-card article-report-score-card">
              <h3>{RU.fullText}</h3>
              <p className="kpi">{report?.full_text_length ?? (paper.fullText?.length || 0)}</p>
              <small>{RU.symbols}</small>
            </article>
          </div>

          <section className="article-section">
            <h3 style={{ marginTop: 0 }}>Рекомендации</h3>
            {report?.recommendations?.length ? (
              <ul>
                {report.recommendations.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : (
              <p className="muted">Рекомендаций нет.</p>
            )}
          </section>

          <section className="article-section">
            <h3 style={{ marginTop: 0 }}>Состав данных</h3>
            <FieldList
              rows={[
                [RU.contentPartsCount, String(contentParts.length)],
                [RU.rawChars, String(rawPartsChars)],
                [RU.aiChars, String(displayedAiChars || markdownPartsChars)],
                [RU.embeddingParts, String(embeddingPartsCount)],
                [RU.keywords, String(report?.keywords_count ?? paper.keywords.length)],
                ["Сгенерирован", report?.generated_at ? formatDateTime(report.generated_at) : RU.unknown],
              ]}
            />
          </section>
        </article>
      )}

      <div className="actions">
        {isAdmin && (
          <button className="btn btn-danger" onClick={onDelete} disabled={actionBusy === "delete"}>
            {actionBusy === "delete" ? RU.actionInProgress : RU.deletePaper}
          </button>
        )}
        <button className="btn" onClick={() => void copyGist()}>{RU.copyGist}</button>
        <button className="btn" onClick={() => navigate("/papers")}>{RU.backToList}</button>
      </div>

      <button
        type="button"
        className="back-to-top-button"
        aria-label="Наверх"
        onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      >
        ↑
      </button>
    </div>
  );
}
