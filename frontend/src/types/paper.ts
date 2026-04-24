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
  createdAt: string | null;
  updatedAt: string | null;
}

const PROCESSING_STATUS_LABELS: Record<string, string> = {
  pending: "Ожидает обработки",
  queued_for_content_processing: "В очереди на обработку",
  processing_content: "Обрабатывается",
  analyzing_ru: "Анализ на русском",
  ready: "Готово",
  ready_with_fallback: "Готово (резервный режим)",
  completed: "Готово",
  failed: "Ошибка обработки",
};

export function getProcessingStatusLabel(status: string | null | undefined): string {
  const key = (status ?? "").trim();
  if (!key) return "Неизвестно";
  return PROCESSING_STATUS_LABELS[key] ?? key;
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

export type CeleryTaskStatusType = "PENDING" | "STARTED" | "RETRY" | "FAILURE" | "SUCCESS";

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
