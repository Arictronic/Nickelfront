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

const PROCESSING_STATUS_LABELS: Record<string, string> = {
  pending: "Ожидает обработки",
  queued_for_content_processing: "В очереди на обработку",
  processing_content: "Обрабатывается",
  started: "Запущено",
  downloading_pdf: "Загрузка PDF",
  pdf_pending: "Ожидание PDF",
  pdf_downloaded: "PDF загружен",
  pdf_parsed: "PDF разобран",
  fulltext_fallback_parsed: "Текст получен (резервный источник)",
  formatting_markdown: "Форматирование текста",
  analyzing_ru: "Анализ на русском",
  extracting_keywords: "Выделение ключевых слов",
  indexing_vector: "Индексация в векторной базе",
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
  pdf_pending: 18,
  downloading_pdf: 28,
  pdf_downloaded: 38,
  pdf_parsed: 48,
  fulltext_fallback_parsed: 48,
  formatting_markdown: 62,
  analyzing_ru: 78,
  extracting_keywords: 86,
  indexing_vector: 92,
  ready: 100,
  ready_with_fallback: 100,
  completed: 100,
  failed: 100,
};

const PROCESSING_FINAL_STATUSES = new Set(["ready", "ready_with_fallback", "completed", "failed"]);

export function getProcessingStatusLabel(status: string | null | undefined): string {
  const key = (status ?? "").trim();
  if (!key) return "Неизвестно";
  return PROCESSING_STATUS_LABELS[key] ?? key;
}

export function getProcessingProgress(status: string | null | undefined): number {
  const key = (status ?? "").trim();
  if (!key) return 0;
  return PROCESSING_STATUS_PROGRESS[key] ?? 0;
}

export function isPaperProcessing(status: string | null | undefined): boolean {
  const key = (status ?? "").trim();
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

export type CeleryTaskStatusType = "PENDING" | "STARTED" | "RETRY" | "FAILURE" | "SUCCESS" | "REVOKED";

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
  embedded_count?: number;
  errors?: string[];
  name?: string;
  args?: any[];
  kwargs?: Record<string, any>;
}

