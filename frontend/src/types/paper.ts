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
  "GooglePatents",
  "PATENTSCOPE",
] as const;

export type PaperSource = (typeof PAPER_SOURCES)[number];
export type PdfProcessingMode = "auto" | "ai" | "mypdf";
export type PaperRegenerationMode = "text" | "image" | "auto" | "mypdf" | "ai";

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
  languageCode: string | null;
  languageName: string | null;
  languageConfidence: number | null;
  languageSource: string | null;
  availableLanguageCodes: string[];
  translationStatus: string | null;
  translationTaskId: string | null;
  translationError: string | null;
  source: PaperSource | string;
  sourceId: string | null;
  canonicalPatentId: string | null;
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
  rank?: number;
  snippet?: string | null;
  titleHighlight?: string | null;
  abstractHighlight?: string | null;
  fullTextHighlight?: string | null;
  hasPdf?: boolean;
  hasFullText?: boolean;
  fullTextIndexed?: boolean;
  matchedFields?: string[];
}

export interface FullTextSearchStats {
  total_matches: number;
  avg_relevance: number;
  max_relevance: number;
}

export interface FullTextSearchResult extends Paper {
  rank: number;
  snippet: string | null;
  titleHighlight: string | null;
  abstractHighlight: string | null;
  fullTextHighlight: string | null;
  hasPdf: boolean;
  hasFullText: boolean;
  fullTextIndexed: boolean;
  matchedFields: string[];
}

export interface PaperContentPartTranslation {
  id: number;
  paperId: number;
  partId: number;
  languageCode: string;
  languageName: string | null;
  sourceLanguageCode: string | null;
  translatedMarkdownText: string | null;
  status: string;
  error: string | null;
  qwenModel: string | null;
  qwenPromptVersion: string | null;
  sourceChars: number;
  translatedChars: number;
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
  contentType: string | null;
  sectionTitle: string | null;
  sectionIndex: number | null;
  pageProfile: string | null;
  includeInEmbedding: boolean;
  qwenModel: string | null;
  qwenPromptVersion: string | null;
  regenerationCount: number;
  rawTextChars: number;
  markdownTextChars: number;
  extractionMethod: string | null;
  extractionQualityScore: number | null;
  extractionWarnings: string[];
  extractionMetadata: Record<string, unknown> | null;
  translations: PaperContentPartTranslation[];
  createdAt: string | null;
  updatedAt: string | null;
}

export interface PaperProcessingStatusInfo {
  key: string;
  label: string;
  group: "pending" | "processing" | "success" | "warning" | "error" | "unknown" | string;
  final: boolean;
  stage?: string;
  stageLabel?: string;
}

export interface PaperPipelineStageInfo {
  key: string;
  label: string;
  status: "pending" | "processing" | "success" | "warning" | "error" | "skipped" | "unknown" | string;
  statusLabel: string;
  progress: number;
  final: boolean;
  enabled: boolean | null;
  skipped: boolean;
  fallbackUsed: boolean;
  error: string | null;
  source: string;
  details: Record<string, unknown>;
}

export interface PaperProcessingPipelineStatus {
  aggregateStatus: "pending" | "processing" | "success" | "warning" | "error" | "unknown" | string;
  aggregateLabel: string;
  aggregateProgress: number;
  hasErrors: boolean;
  hasWarnings: boolean;
  pdfStage: PaperPipelineStageInfo;
  ocrStage: PaperPipelineStageInfo;
  markdownStage: PaperPipelineStageInfo;
  ruAnalysisStage: PaperPipelineStageInfo;
  keywordsStage: PaperPipelineStageInfo;
  embeddingStage: PaperPipelineStageInfo;
  finalStage: PaperPipelineStageInfo;
  stages: PaperPipelineStageInfo[];
}

export interface PaperProcessingQualityInfo {
  mode: PdfProcessingMode | "mixed" | "unknown" | string;
  score: number | null;
  label: string;
  basis: string;
  status: "success" | "warning" | "error" | "unknown" | string;
  pagesTotal?: number | null;
  pagesSuccess?: number | null;
  pagesFailed?: number | null;
  fallbackUsed?: boolean;
  requestedMode?: string | null;
  actualMode?: string | null;
}

export interface PaperContentPartRegenerateResponse {
  paper_id: number;
  part_id: number;
  task_id: string;
  status: string;
  page_start: number;
  page_end: number;
  mode: PaperRegenerationMode;
}

export interface PaperTranslateResponse {
  paper_id: number;
  task_id: string;
  status: string;
  target_language_code: string;
  target_language_name: string | null;
  parts_total: number;
  parts_ready: number;
}

export interface PaperReportData {
  paper_id: number;
  title: string;
  authors: string[];
  journal: string | null;
  publication_date: string | null;
  doi: string | null;
  source: string;
  abstract_length: number;
  full_text_length: number;
  keywords_count: number;
  scores: {
    quality_score: number;
    completeness_score: number;
  };
  recommendations: string[];
  generated_at: string;
}

export interface PaperDetailResponse {
  paper: Paper;
  contentParts: PaperContentPart[];
  statusInfo: PaperProcessingStatusInfo;
  processingQuality: PaperProcessingQualityInfo | null;
  pipelineStatus: PaperProcessingPipelineStatus | null;
}

const PROCESSING_STATUS_LABELS: Record<string, string> = {
  pending: "Ожидает обработки",
  queued_for_content_processing: "В очереди на обработку",
  processing_content: "Обрабатывается",
  content_queue_failed: "Ошибка постановки content pipeline",
  started: "Запущено",
  pdf_pending: "Подготовка PDF",
  downloading_pdf: "Загрузка PDF",
  pdf_downloaded: "PDF загружен",
  pdf_download_failed: "PDF не загрузился",
  pdf_download_skipped: "Загрузка PDF пропущена",
  pdf_unavailable: "PDF недоступен",
  extracting_pdf_text: "Извлечение текста из PDF",
  pdf_text_skipped: "Извлечение текста PDF пропущено",
  pdf_parsed: "Текст PDF извлечён",
  pdf_text_failed: "Ошибка извлечения текста PDF",
  fulltext_fallback_parsed: "Текст получен из резервного источника",
  fulltext_unavailable: "Полный текст недоступен",
  formatting_markdown: "Оцифровка файла",
  digitizing_file: "Оцифровка файла",
  markdown_ready: "Файл оцифрован",
  markdown_partial: "Файл частично оцифрован",
  markdown_ready_without_qwen: "Текст собран без Qwen",
  page_regenerated: "Страница переоцифрована",
  markdown_failed: "Ошибка оцифровки файла",
  markdown_skipped: "Оцифровка пропущена",
  analyzing_ru: "Анализ на русском",
  ru_analysis_ready: "Русский анализ готов",
  ru_analysis_failed: "Ошибка русского анализа",
  ru_analysis_fallback: "Русский анализ в резервном режиме",
  ru_analysis_skipped: "Русский анализ пропущен",
  translating_article: "Перевод текста статьи",
  translation_ready: "Перевод текста готов",
  translation_partial: "Перевод текста частично готов",
  translation_failed: "Ошибка перевода текста",
  extracting_keywords: "Выделение ключевых слов",
  keywords_ready: "Ключевые слова готовы",
  keywords_failed: "Ошибка ключевых слов",
  keywords_skipped: "Ключевые слова пропущены",
  indexing_vector: "Индексация в векторной базе",
  embedding_ready: "Векторный индекс готов",
  embedding_failed: "Ошибка векторной индексации",
  embedding_skipped: "Векторная индексация пропущена",
  qwen_auth_failed: "Ошибка авторизации Qwen",
  ready: "Готово",
  ready_with_fallback: "Готово (резервный режим)",
  completed: "Готово",
  failed: "Ошибка обработки",
};

const PROCESSING_STATUS_PROGRESS: Record<string, number> = {
  pending: 0,
  queued_for_content_processing: 5,
  processing_content: 10,
  content_queue_failed: 10,
  started: 12,
  pdf_pending: 15,
  downloading_pdf: 25,
  pdf_downloaded: 32,
  pdf_download_failed: 35,
  pdf_download_skipped: 35,
  pdf_unavailable: 35,
  extracting_pdf_text: 40,
  pdf_text_skipped: 48,
  pdf_parsed: 48,
  pdf_text_failed: 48,
  fulltext_fallback_parsed: 48,
  fulltext_unavailable: 48,
  formatting_markdown: 52,
  digitizing_file: 52,
  markdown_ready: 72,
  markdown_partial: 72,
  markdown_ready_without_qwen: 72,
  page_regenerated: 100,
  markdown_failed: 72,
  markdown_skipped: 72,
  analyzing_ru: 80,
  ru_analysis_ready: 86,
  ru_analysis_failed: 86,
  ru_analysis_fallback: 86,
  ru_analysis_skipped: 86,
  translating_article: 88,
  translation_ready: 100,
  translation_partial: 96,
  translation_failed: 96,
  extracting_keywords: 90,
  keywords_ready: 92,
  keywords_failed: 92,
  keywords_skipped: 92,
  indexing_vector: 96,
  embedding_ready: 96,
  embedding_failed: 96,
  embedding_skipped: 96,
  qwen_auth_failed: 80,
  ready: 100,
  ready_with_fallback: 100,
  completed: 100,
  failed: 100,
};

const PROCESSING_FINAL_STATUSES = new Set([
  "ready",
  "ready_with_fallback",
  "completed",
  "failed",
  // Translation statuses are final for the translation action, not for the
  // AI/PDF/Qwen document pipeline. They are kept here for legacy widgets that
  // still receive translation status through processingStatus.
  "translation_ready",
  "translation_partial",
  "translation_failed",
]);

type ParsedProcessingStatus = {
  key: string;
  current: number | null;
  total: number | null;
};

function parseProcessingStatus(
  status: string | null | undefined,
): ParsedProcessingStatus {
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

export function getProcessingStatusKey(
  status: string | null | undefined,
): string {
  return parseProcessingStatus(status).key;
}

export function getProcessingStatusLabel(
  status: string | null | undefined,
): string {
  const parsed = parseProcessingStatus(status);
  if (!parsed.key) return "Неизвестно";

  const baseLabel = PROCESSING_STATUS_LABELS[parsed.key] ?? parsed.key;
  if (
    (parsed.key === "digitizing_file" || parsed.key === "translating_article") &&
    parsed.current !== null &&
    parsed.total !== null &&
    parsed.total > 0
  ) {
    const unit = parsed.key === "translating_article" ? "част." : "стр.";
    return `${baseLabel} — ${Math.min(parsed.current, parsed.total)}/${parsed.total} ${unit}`;
  }

  return baseLabel;
}

export function getProcessingProgress(
  status: string | null | undefined,
): number {
  const parsed = parseProcessingStatus(status);
  if (!parsed.key) return 0;

  if (
    (parsed.key === "digitizing_file" || parsed.key === "translating_article") &&
    parsed.current !== null &&
    parsed.total !== null &&
    parsed.total > 0
  ) {
    const pageRatio = Math.max(0, Math.min(1, parsed.current / parsed.total));
    if (parsed.key === "translating_article") {
      return Math.max(88, Math.min(96, Math.round(88 + pageRatio * 8)));
    }
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
  translationStatus?: string;
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

export type CeleryTaskStatusType =
  | "PENDING"
  | "RECEIVED"
  | "STARTED"
  | "PROGRESS"
  | "RETRY"
  | "FAILURE"
  | "SUCCESS"
  | "REVOKED"
  | "UNKNOWN";

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
