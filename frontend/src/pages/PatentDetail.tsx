import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  deletePaper,
  getPaperById,
  getPaperContentParts,
  getPaperPdfUrl,
  regeneratePaperContentPart,
  regeneratePaperMarkdownPages,
  reprocessPaperContent,
} from "../api/papers";
import { getPublicDisplaySettings } from "../api/settings";
import { useToast } from "../components/ui/Toast";
import type { Paper, PaperContentPart } from "../types/paper";
import {
  getProcessingProgress,
  getProcessingStatusLabel,
  isPaperProcessing,
} from "../types/paper";

type Tab = "main" | "parts" | "report";
type BusyAction = "delete" | "reprocess" | null;
type TextViewMode = "raw" | "ai";

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
  status: "Статус обработки",
  fullText: "Полный текст",
  yes: "Есть",
  no: "Нет",
  open: "Открыть",
  openPdf: "Открыть PDF",
  workerTask: "Worker task",
  tabMain: "Главная",
  tabParts: "Текст по страницам",
  tabReport: "Отчет",
  gist: "Суть статьи",
  gistNotReady: "Здесь будет короткий пересказ всего документа: о чём он, какие ключевые результаты и почему он полезен для анализа.",
  pdfLen: "PDF",
  articleText: "Текст статьи",
  reportBtn: "Открыть отчет на отдельной странице",
  reprocessBtn: "Перезапустить обработку всего документа",
  parts: "Текст по страницам",
  emptyText: "Текст пуст.",
  selectedPart: "Выбранная страница",
  localMetrics: "Локальные метрики (эвристики)",
  localMetricsHint: "Быстрый локальный разбор выбранной части без обращения к AI.",
  temps: "Температуры (°C)",
  aiAnalysis: "AI анализ (русский)",
  aiNotReady: "Анализ ещё не готов.",
  translation: "Перевод (русский)",
  translationNotReady: "Перевод ещё не готов.",
  processingError: "Ошибка обработки",
  noTextForReport: "Нет текста для отчета.",
  quickOverview: "Страницы (быстрый обзор)",
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
  noStoredParts: "Сохранённых страниц пока нет. Показываю legacy-разбиение полного текста.",
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
      sourcePartIds: [],
    });
  }
  return chunks;
}

function mapStoredPart(part: PaperContentPart): DisplayPart {
  const title = pageTitle(part.pageStart, part.pageEnd, `Часть ${part.partIndex}`);
  return {
    id: part.id,
    title,
    pageStart: part.pageStart,
    pageEnd: part.pageEnd,
    markdown: part.markdownText || "",
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

function aggregateStoredPartsByPage(parts: PaperContentPart[]): DisplayPart[] {
  const groups = new Map<string, PaperContentPart[]>();

  for (const part of parts) {
    const key = `${part.pageStart}-${part.pageEnd}`;
    const current = groups.get(key) ?? [];
    current.push(part);
    groups.set(key, current);
  }

  return Array.from(groups.values()).map((group) => {
    const first = group[0];

    if (group.length === 1) return mapStoredPart(first);

    const rawText = group
      .map((part) => part.rawText?.trim() ?? "")
      .filter(Boolean)
      .join("\n\n");

    const markdown = group
      .map((part) => part.markdownText?.trim() ?? "")
      .filter(Boolean)
      .join("\n\n");

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
      sourcePartIds,
    };
  });
}

function getRegenerationKey(part: DisplayPart | null): string | null {
  if (!part) return null;
  if (part.id) return `part-${part.id}`;
  if (part.pageStart && part.pageEnd) return `pages-${part.pageStart}-${part.pageEnd}`;
  return null;
}


function localExtractMetrics(text: string) {
  const lower = text.toLowerCase();
  const keywords = [
    "nickel",
    "superalloy",
    "inconel",
    "hastelloy",
    "creep",
    "tensile",
    "fatigue",
    "yield",
    "temperature",
    "corrosion",
  ];
  const found: Record<string, number> = {};
  for (const k of keywords) {
    const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
    const m = lower.match(re);
    found[k] = m ? m.length : 0;
  }

  const temps = (text.match(/(\d+(?:\.\d+)?)\s*(?:°\s*)?c/gi) ?? []).slice(0, 20);
  const topKeywords = Object.entries(found)
    .sort((a, b) => b[1] - a[1])
    .filter(([, v]) => v > 0)
    .slice(0, 8);

  return { topKeywords, temps };
}


function normalizePartStatus(status: string | null | undefined): string {
  return (status || "").trim().toLowerCase();
}

const PDF_WARNING_LABELS: Record<string, string> = {
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
  if (part.markdown?.trim() && part.markdownTextChars > 0) {
    return { key: "ai_ready", label: "Готово", tone: "success" };
  }
  if (status === "processing") return { key: "ai_processing", label: "В обработке", tone: "processing" };
  if (status === "failed" || part.error) return { key: "ai_pending_after_error", label: "В очереди", tone: "pending", detail: part.error || undefined };
  if (status === "raw_extracted") return { key: "ai_waiting_raw", label: "В очереди", tone: "pending" };
  if (status === "ready" && !part.markdownTextChars) return { key: "ai_skipped", label: "В очереди", tone: "neutral" };
  if (status === "legacy" && part.markdown?.trim()) return { key: "ai_legacy", label: "Готово", tone: "success" };
  return { key: "ai_pending", label: "В очереди", tone: "pending" };
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


function MarkdownText({ text }: { text: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        skipHtml
      >
        {normalizeMarkdownForDisplay(text)}
      </ReactMarkdown>
    </div>
  );
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

  const [paper, setPaper] = useState<Paper | null>(null);
  const [contentParts, setContentParts] = useState<PaperContentPart[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pollingWarning, setPollingWarning] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("main");
  const [activePartIndex, setActivePartIndex] = useState(0);
  const [textViewMode, setTextViewMode] = useState<TextViewMode>("ai");
  const [showExtractionDiagnostics, setShowExtractionDiagnostics] = useState(true);
  const [actionBusy, setActionBusy] = useState<BusyAction>(null);
  const [regeneratingPartKey, setRegeneratingPartKey] = useState<string | null>(null);

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
      const nextPaper = await getPaperById(paperId);
      setPaper(nextPaper);
      try {
        const nextParts = await getPaperContentParts(paperId);
        setContentParts(nextParts);
      } catch (partsError) {
        setContentParts([]);
        console.warn("Failed to load paper content parts", partsError);
      }
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
    loadPaper();
    getPublicDisplaySettings()
      .then((value) => setShowExtractionDiagnostics(value.show_extraction_diagnostics ?? true))
      .catch(() => setShowExtractionDiagnostics(true));
  }, [id]);

  useEffect(() => {
    if (!paper || !isPaperProcessing(paper.processingStatus)) return;
    const timer = window.setInterval(() => {
      loadPaper(false).catch(() => null);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [paper?.id, paper?.processingStatus]);

  const fullText = paper?.fullText ?? "";
  const hasFullText = Boolean(fullText.trim().length);
  const hasFullTextOrPdf = Boolean(hasFullText || paper?.pdfUrl || paper?.pdfLocalPath);

  const displayParts = useMemo<DisplayPart[]>(() => {
    if (contentParts.length) return aggregateStoredPartsByPage(contentParts);
    return splitLegacyMarkdownParts(fullText);
  }, [contentParts, fullText]);

  const selectedPart = displayParts[activePartIndex] ?? null;

  useEffect(() => {
    if (tab === "parts" && !hasFullText && !displayParts.length) setTab("main");
  }, [tab, hasFullText, displayParts.length]);

  useEffect(() => {
    if (activePartIndex >= displayParts.length) setActivePartIndex(0);
  }, [activePartIndex, displayParts.length]);

  const activeLayerStatus = useMemo(
    () => (textViewMode === "raw" ? getRawPartStatus(selectedPart) : getAiPartStatus(selectedPart)),
    [selectedPart, textViewMode],
  );

  const rawOverallStatus = useMemo(() => getOverallLayerStatus(displayParts, "raw"), [displayParts]);
  const aiOverallStatus = useMemo(() => getOverallLayerStatus(displayParts, "ai"), [displayParts]);

  const partMetrics = useMemo(() => {
    if (!selectedPart) return null;
    const text = textViewMode === "raw" ? selectedPart.rawText || "" : selectedPart.markdown || "";
    return localExtractMetrics(text || selectedPart.markdown || selectedPart.rawText || "");
  }, [selectedPart, textViewMode]);

  const onDelete = async () => {
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
    if (!paper || actionBusy) return;
    setActionBusy("reprocess");
    setActionError(null);
    try {
      await reprocessPaperContent(paper.id);
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

  const onRegeneratePart = async (part: DisplayPart) => {
    const key = getRegenerationKey(part);
    if (!paper || !key || regeneratingPartKey) return;
    setRegeneratingPartKey(key);
    setActionError(null);
    try {
      if (part.id) {
        await regeneratePaperContentPart(paper.id, part.id);
      } else if (part.pageStart && part.pageEnd) {
        await regeneratePaperMarkdownPages(paper.id, part.pageStart, part.pageEnd);
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

  if (loading) return <p className="muted">{RU.loading}</p>;
  if (loadError && !paper) return <p className="error">{loadError}</p>;
  if (!paper) return <p className="muted">{RU.notFound}</p>;

  return (
    <div className="page">
      <p className="muted">
        <Link to="/dashboard">{RU.home}</Link> → <Link to="/papers">{RU.papers}</Link> → {paper.title}
      </p>

      {actionError && <p className="error">{actionError}</p>}
      {pollingWarning && <p className="muted">{pollingWarning}</p>}

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>{paper.title}</h2>
        <div className="detail-grid">
          <p><strong>{RU.authors}:</strong> {paper.authors.length ? paper.authors.slice(0, 4).join(", ") + (paper.authors.length > 4 ? "..." : "") : RU.unknown}</p>
          <p><strong>{RU.source}:</strong> {paper.source}</p>
          <p><strong>{RU.date}:</strong> {paper.publicationDate ? paper.publicationDate.slice(0, 10) : RU.unknown}</p>
          <p><strong>{RU.journal}:</strong> {paper.journal ?? RU.unknown}</p>
          <p><strong>DOI:</strong> {paper.doi ?? RU.unknown}</p>
          <p><strong>{RU.keywords}:</strong> {paper.keywords.length ? paper.keywords.slice(0, 10).join(", ") : RU.unknown}</p>
          <div className="detail-progress">
            <div className="paper-progress-head">
              <strong>{RU.status}:</strong>
              <span>{getProcessingStatusLabel(paper.processingStatus)} - {getProcessingProgress(paper.processingStatus)}%</span>
            </div>
            <div className="paper-progress-track" aria-label={`paper-${paper.id}-progress`}>
              <div
                className={`paper-progress-fill ${paper.processingStatus === "failed" ? "failed" : getProcessingProgress(paper.processingStatus) === 100 ? "done" : ""}`}
                style={{ width: `${Math.max(3, getProcessingProgress(paper.processingStatus))}%` }}
              />
            </div>
          </div>
          <p><strong>{RU.fullText}:</strong> {hasFullTextOrPdf ? RU.yes : RU.no}</p>
          <p><strong>URL:</strong> {paper.url ? <a href={paper.url} target="_blank" rel="noreferrer" className="action-link">{RU.open}</a> : RU.unknown}</p>
          <p><strong>PDF:</strong> {paper.pdfUrl || paper.pdfLocalPath ? <a href={getPaperPdfUrl(paper.id)} target="_blank" rel="noreferrer" className="action-link">{RU.openPdf}</a> : RU.unknown}</p>
          <p><strong>{RU.workerTask}:</strong> {paper.contentTaskId ?? RU.unknown}</p>
        </div>
      </div>

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

          {(paper.pdfUrl || paper.pdfLocalPath) && (
            <section className="article-section">
              <h2 className="article-section-title">{RU.pdfLen}</h2>
              <iframe
                title="paper-pdf"
                src={getPaperPdfUrl(paper.id)}
                className="article-pdf-frame"
              />
            </section>
          )}

          {(paper.fullText || displayParts.length > 0) && (
            <section className="article-section article-text-section">
              <div className="article-section-head">
                <h2 className="article-section-title">{RU.articleText}</h2>
                <StatusPill status={textViewMode === "raw" ? rawOverallStatus : aiOverallStatus} />
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

                  {textViewMode === "raw" && showExtractionDiagnostics && rawOverallStatus.detail && (
                    <p className="article-text-integrity">{rawOverallStatus.detail}</p>
                  )}

                  <div className="article-text-scroll-panel">
                    <div className="markdown-parts-readable">
                      {displayParts.map((part, idx) => {
                        const rawStatus = getRawPartStatus(part);
                        const aiStatus = getAiPartStatus(part);
                        const text = textViewMode === "raw" ? part.rawText || "" : part.markdown || "";
                        return (
                          <section className="markdown-part-readonly" key={`${part.id ?? "legacy"}-${idx}`}>
                            <div className="markdown-part-header compact">
                              <div>
                                <h4>{part.title}</h4>
                                <div className="part-status-row compact-row">
                                  <StatusPill status={textViewMode === "raw" ? rawStatus : aiStatus} />
                                </div>
                                {textViewMode === "raw" && showExtractionDiagnostics && (
                                  <PartExtractionInfo part={part} compact />
                                )}
                              </div>
                              {textViewMode === "ai" && (
                                <button
                                  className="btn btn-primary"
                                  disabled={!getRegenerationKey(part) || regeneratingPartKey === getRegenerationKey(part)}
                                  onClick={() => onRegeneratePart(part)}
                                  title={!getRegenerationKey(part) ? "Перегенерация доступна только для сохранённых страниц" : undefined}
                                >
                                  {regeneratingPartKey === getRegenerationKey(part) ? RU.regenerating : RU.regenerate}
                                </button>
                              )}
                            </div>
                            {textViewMode === "raw" ? (
                              text.trim() ? <PlainTextDocument text={text} /> : <p className="muted">{RU.rawNotAvailable}</p>
                            ) : (
                              text.trim() ? <MarkdownText text={text} /> : <p className="muted">{RU.aiNotAvailable}</p>
                            )}
                          </section>
                        );
                      })}
                    </div>
                  </div>
                </>
              ) : (
                <MarkdownText text={paper.fullText ?? ""} />
              )}
            </section>
          )}

          <div className="article-actions-row">
            <button className="btn" onClick={() => navigate(`/papers/${paper.id}/report`)}>{RU.reportBtn}</button>
            <button className="btn" onClick={onReprocess} disabled={actionBusy === "reprocess"}>
              {actionBusy === "reprocess" ? RU.actionInProgress : RU.reprocessBtn}
            </button>
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
                        <StatusPill status={textViewMode === "raw" ? getRawPartStatus(selectedPart) : getAiPartStatus(selectedPart)} />
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
                      <button
                        className="btn btn-primary"
                        disabled={!getRegenerationKey(selectedPart) || regeneratingPartKey === getRegenerationKey(selectedPart)}
                        onClick={() => onRegeneratePart(selectedPart)}
                        title={!getRegenerationKey(selectedPart) ? "Перегенерация доступна только для сохранённых страниц" : undefined}
                      >
                        {regeneratingPartKey === getRegenerationKey(selectedPart) ? RU.regenerating : RU.regenerate}
                      </button>
                    </div>
                  </div>

                  {selectedPart.error && <p className="error">{selectedPart.error}</p>}

                  <div className="selected-layer-status">
                    <StatusPill status={activeLayerStatus} />
                    {textViewMode === "raw" && showExtractionDiagnostics && activeLayerStatus.detail && (
                      <span className="muted">{activeLayerStatus.detail}</span>
                    )}
                  </div>

                  {textViewMode === "raw" ? (
                    selectedPart.rawText?.trim() ? <PlainTextDocument text={selectedPart.rawText} /> : <p className="muted">{RU.rawNotAvailable}</p>
                  ) : (
                    selectedPart.markdown?.trim() ? <MarkdownText text={selectedPart.markdown} /> : <p className="muted">{RU.aiNotAvailable}</p>
                  )}

                  <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "14px 0" }} />
                  <h3 style={{ marginTop: 0 }}>{RU.localMetrics}</h3>
                  <p className="muted">{RU.localMetricsHint}</p>
                  {partMetrics && (
                    <div className="detail-grid" style={{ marginTop: 10 }}>
                      <p><strong>Top keywords:</strong> {partMetrics.topKeywords.length ? partMetrics.topKeywords.map(([k, v]) => `${k}=${v}`).join(", ") : RU.unknown}</p>
                      <p><strong>{RU.temps}:</strong> {partMetrics.temps.length ? partMetrics.temps.join(", ") : RU.unknown}</p>
                    </div>
                  )}
                </>
              ) : <p className="muted">{RU.emptyText}</p>}
            </div>
          </div>
        </article>
      )}

      {tab === "report" && (
        <article className="panel">
          <h3>{RU.aiAnalysis}</h3>
          {paper.analysisRu ? <p style={{ whiteSpace: "pre-wrap" }}>{paper.analysisRu}</p> : <p className="muted">{RU.aiNotReady}</p>}

          <h3 style={{ marginTop: 18 }}>{RU.translation}</h3>
          {paper.translationRu ? <p style={{ whiteSpace: "pre-wrap" }}>{paper.translationRu}</p> : <p className="muted">{RU.translationNotReady}</p>}

          {paper.processingError && <p className="error" style={{ marginTop: 12 }}>{RU.processingError}: {paper.processingError}</p>}

          {!displayParts.length ? <p className="muted">{RU.noTextForReport}</p> : (
            <>
              <h3>{RU.quickOverview}</h3>
              <div className="markdown-parts-overview">
                {displayParts.slice(0, 8).map((part, idx) => {
                  const m = localExtractMetrics(part.markdown);
                  return (
                    <article className="panel" key={`${part.id ?? "legacy"}-${idx}`} style={{ boxShadow: "none", padding: 12 }}>
                      <p className="muted">{part.title}</p>
                      <p style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 13 }}>
                        {(m.topKeywords.length ? m.topKeywords.map(([k, v]) => `${k}:${v}`).join(", ") : "метрики не найдены") + "\n\n"}
                        {part.markdown.slice(0, 300)}...
                      </p>
                    </article>
                  );
                })}
              </div>
              {displayParts.length > 8 && <p className="muted">Показаны первые 8 частей.</p>}
            </>
          )}
        </article>
      )}

      <div className="actions">
        <button className="btn btn-danger" onClick={onDelete} disabled={actionBusy === "delete"}>
          {actionBusy === "delete" ? RU.actionInProgress : RU.deletePaper}
        </button>
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
