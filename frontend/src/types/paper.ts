export const PAPER_SOURCES = [
  "CORE",
  "arXiv",
  "OpenAlex",
  "Crossref",
  "EuropePMC",
  "CyberLeninka",
  "eLibrary",
  "Rospatent",
  "FreePatent",
  "PATENTSCOPE",
] as const;

export type PaperSource = (typeof PAPER_SOURCES)[number];

export interface Paper {
  id: number;
  title: string;
  authors: string[];
  publicationDate: string | null;
  journal: string | null;
  doi: string | null;
  abstract: string | null;
  fullText: string | null;
  keywords: string[];
  source: PaperSource | string;
  sourceId: string | null;
  url: string | null;
  pdfUrl: string | null;
  pdfLocalPath: string | null;
  processingStatus: string;
  contentTaskId: string | null;
  processingError: string | null;
  summaryRu: string | null;
  analysisRu: string | null;
  translationRu: string | null;
  parseConfidence: number | null;
  provenance: Record<string, string>;
  qualityFlags: string[];
  schemaVersion: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface PaperContentPart {
  id: number;
  paperId: number;
  partIndex: number;
  pageStart: number;
  pageEnd: number;
  rawText: string | null;
  markdownText: string | null;
  status: string;
  error: string | null;
  source: string;
  qwenModel: string | null;
  qwenPromptVersion: string | null;
  regenerationCount: number;
  rawTextChars: number;
  markdownTextChars: number;
  extractionMethod: string | null;
  extractionQualityScore: number | null;
  extractionWarnings: string[];
  extractionMetadata: Record<string, unknown> | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface PaperContentPartRegenerateResponse {
  paper_id: number;
  part_id: number;
  task_id: string;
  status: string;
  page_start: number;
  page_end: number;
}

const PROCESSING_STATUS_LABELS: Record<string, string> = {
  pending: "Ожидает обработки",
  queued_for_content_processing: "В очереди на обработку",
  processing_content: "Обрабатывается",
  started: "Запущено",
  pdf_pending: "Подготовка PDF",
  downloading_pdf: "Загрузка PDF",
  pdf_downloaded: "PDF загружен",
  pdf_download_failed: "PDF не загрузился",
  pdf_unavailable: "PDF недоступен",
  extracting_pdf_text: "Извлечение текста из PDF",
  pdf_parsed: "Текст PDF извлечён",
  fulltext_fallback_parsed: "Текст получен из резервного источника",
  fulltext_unavailable: "Полный текст недоступен",
  formatting_markdown: "Оцифровка файла",
  digitizing_file: "Оцифровка файла",
  markdown_ready: "Файл оцифрован",
  markdown_failed: "Ошибка оцифровки файла",
  markdown_skipped: "Оцифровка пропущена",
  analyzing_ru: "Анализ на русском",
  ru_analysis_ready: "Русский анализ готов",
  ru_analysis_fallback: "Русский анализ в резервном режиме",
  extracting_keywords: "Выделение ключевых слов",
  keywords_ready: "Ключевые слова готовы",
  keywords_failed: "Ошибка ключевых слов",
  indexing_vector: "Индексация в векторной базе",
  embedding_ready: "Векторный индекс готов",
  embedding_skipped: "Векторная индексация пропущена",
  ready: "Готово",
  ready_with_fallback: "Готово (резервный режим)",
  completed: "Готово",
  failed: "Ошибка обработки",
};

const PROCESSING_STATUS_PROGRESS: Record<string, number> = {
  pending: 0,
  queued_for_content_processing: 5,
  processing_content: 10,
  started: 12,
  pdf_pending: 15,
  downloading_pdf: 25,
  pdf_downloaded: 32,
  pdf_download_failed: 35,
  pdf_unavailable: 35,
  extracting_pdf_text: 40,
  pdf_parsed: 48,
  fulltext_fallback_parsed: 48,
  fulltext_unavailable: 48,
  formatting_markdown: 52,
  digitizing_file: 52,
  markdown_ready: 72,
  markdown_failed: 72,
  markdown_skipped: 72,
  analyzing_ru: 80,
  ru_analysis_ready: 86,
  ru_analysis_fallback: 86,
  extracting_keywords: 90,
  keywords_ready: 92,
  keywords_failed: 92,
  indexing_vector: 96,
  embedding_ready: 98,
  embedding_skipped: 98,
  ready: 100,
  ready_with_fallback: 100,
  completed: 100,
  failed: 100,
};

const PROCESSING_FINAL_STATUSES = new Set(["ready", "ready_with_fallback", "completed", "failed"]);

type ParsedProcessingStatus = {
  key: string;
  current: number | null;
  total: number | null;
};

function parseProcessingStatus(status: string | null | undefined): ParsedProcessingStatus {
  const raw = (status ?? "").trim();
  if (!raw) return { key: "", current: null, total: null };

  const match = raw.match(/^([a-z_]+):(\d+)\/(\d+)$/i);
  if (!match) return { key: raw, current: null, total: null };

  const current = Number(match[2]);
  const total = Number(match[3]);
  return {
    key: match[1],
    current: Number.isFinite(current) ? current : null,
    total: Number.isFinite(total) ? total : null,
  };
}

export function getProcessingStatusKey(status: string | null | undefined): string {
  return parseProcessingStatus(status).key;
}

export function getProcessingStatusLabel(status: string | null | undefined): string {
  const parsed = parseProcessingStatus(status);
  if (!parsed.key) return "Неизвестно";

  const baseLabel = PROCESSING_STATUS_LABELS[parsed.key] ?? parsed.key;
  if (
    parsed.key === "digitizing_file" &&
    parsed.current !== null &&
    parsed.total !== null &&
    parsed.total > 0
  ) {
    return `${baseLabel} — ${Math.min(parsed.current, parsed.total)}/${parsed.total} стр.`;
  }

  return baseLabel;
}

export function getProcessingProgress(status: string | null | undefined): number {
  const parsed = parseProcessingStatus(status);
  if (!parsed.key) return 0;

  if (
    parsed.key === "digitizing_file" &&
    parsed.current !== null &&
    parsed.total !== null &&
    parsed.total > 0
  ) {
    const pageRatio = Math.max(0, Math.min(1, parsed.current / parsed.total));
    return Math.max(52, Math.min(72, Math.round(52 + pageRatio * 20)));
  }

  return PROCESSING_STATUS_PROGRESS[parsed.key] ?? 0;
}

export function isPaperProcessing(status: string | null | undefined): boolean {
  const key = getProcessingStatusKey(status);
  return Boolean(key && !PROCESSING_FINAL_STATUSES.has(key));
}

export interface PaperSearchFilters {
  query: string;
  sources: PaperSource[];
  fullTextOnly: boolean;
  limit: number;
}

export interface PaperListFilters {
  source?: PaperSource | "all";
  fullTextOnly: boolean;
  dateFrom?: string; // yyyy-mm-dd
  dateTo?: string; // yyyy-mm-dd
  query?: string;
  processingStatus?: string;
}

export type SearchType = "vector" | "semantic" | "hybrid" | "text";

export interface VectorSearchFilters {
  query: string;
  limit: number;
  source?: PaperSource | "all";
  dateFrom?: string;
  dateTo?: string;
  searchType: SearchType;
}

export interface VectorSearchResult {
  paper: Paper;
  similarity: number;
}

export interface VectorSearchResponse {
  results: VectorSearchResult[];
  total: number;
  query: string;
  search_type: SearchType | "text_fallback";
}

export type CeleryTaskStatusType = "PENDING" | "RECEIVED" | "STARTED" | "PROGRESS" | "RETRY" | "FAILURE" | "SUCCESS" | "REVOKED" | "UNKNOWN";

export interface CeleryTaskStatus {
  task_id: string;
  status: CeleryTaskStatusType;
  state?: string;
  result?: {
    query?: string;
    source?: string;
    current?: number;
    total?: number;
    saved_count?: number;
    updated_count?: number;
    duplicate_count?: number;
    embedded_count?: number;
    errors?: string[];
    [key: string]: any;
  };
  progress?: {
    current?: number;
    total?: number;
    [key: string]: any;
  };
  query?: string;
  source?: string;
  current?: number;
  total?: number;
  saved_count?: number;
  updated_count?: number;
  duplicate_count?: number;
  embedded_count?: number;
  errors?: string[];
  name?: string;
  args?: any[];
  kwargs?: Record<string, any>;
}

