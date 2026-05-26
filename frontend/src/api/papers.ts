import { apiClient } from "./client";
import type {
  Paper,
  PaperListFilters,
  PaperSearchFilters,
  PaperSource,
  PdfProcessingMode,
  PaperContentPart,
  PaperContentPartRegenerateResponse,
  FullTextSearchResult,
  FullTextSearchStats,
} from "../types/paper";
import type { VectorSearchFilters, VectorSearchResponse } from "../types/paper";

const HTML_TAG_RE = /<[^>]+>/g;
function stripHtml(value: string | null | undefined): string | null {
  if (!value) return null;
  const cleaned = value.replace(HTML_TAG_RE, " ").replace(/\s+/g, " ").trim();
  return cleaned || null;
}

type PaperApiModel = {
  id: number;
  title: string;
  authors: string[];
  publication_date: string | null;
  journal: string | null;
  doi: string | null;
  abstract: string | null;
  full_text?: string | null;
  keywords: string[];
  source: PaperSource | string;
  source_id: string | null;
  url: string | null;
  pdf_url: string | null;
  pdf_local_path: string | null;
  processing_status: string;
  content_task_id: string | null;
  processing_error: string | null;
  summary_ru: string | null;
  analysis_ru: string | null;
  translation_ru: string | null;
  parse_confidence: number | null;
  provenance: Record<string, string> | null;
  quality_flags: string[] | null;
  schema_version: string | null;
  created_at: string | null;
  updated_at: string | null;
  rank?: number | null;
  snippet?: string | null;
  title_highlight?: string | null;
  abstract_highlight?: string | null;
  full_text_highlight?: string | null;
  has_pdf?: boolean | null;
  has_full_text?: boolean | null;
  full_text_indexed?: boolean | null;
  matched_fields?: string[] | null;
};

type PaperContentPartApiModel = {
  id: number;
  paper_id: number;
  part_index: number;
  page_start: number;
  page_end: number;
  raw_text: string | null;
  markdown_text: string | null;
  status: string;
  error: string | null;
  source: string;
  content_type?: string | null;
  section_title?: string | null;
  section_index?: number | null;
  page_profile?: string | null;
  include_in_embedding?: boolean | null;
  qwen_model: string | null;
  qwen_prompt_version: string | null;
  regeneration_count: number;
  raw_text_chars: number;
  markdown_text_chars: number;
  extraction_method?: string | null;
  extraction_quality_score?: number | null;
  extraction_warnings?: string[] | null;
  extraction_metadata?: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
};

function mapPaperContentPart(
  apiPart: PaperContentPartApiModel,
): PaperContentPart {
  return {
    id: apiPart.id,
    paperId: apiPart.paper_id,
    partIndex: apiPart.part_index,
    pageStart: apiPart.page_start,
    pageEnd: apiPart.page_end,
    rawText: apiPart.raw_text ?? null,
    markdownText: apiPart.markdown_text ?? null,
    status: apiPart.status ?? "raw_extracted",
    error: apiPart.error ?? null,
    source: apiPart.source ?? "pdf",
    contentType: apiPart.content_type ?? null,
    sectionTitle: apiPart.section_title ?? null,
    sectionIndex: apiPart.section_index ?? null,
    pageProfile: apiPart.page_profile ?? null,
    includeInEmbedding: apiPart.include_in_embedding ?? true,
    qwenModel: apiPart.qwen_model ?? null,
    qwenPromptVersion: apiPart.qwen_prompt_version ?? null,
    regenerationCount: apiPart.regeneration_count ?? 0,
    rawTextChars: apiPart.raw_text_chars ?? 0,
    markdownTextChars: apiPart.markdown_text_chars ?? 0,
    extractionMethod: apiPart.extraction_method ?? null,
    extractionQualityScore: apiPart.extraction_quality_score ?? null,
    extractionWarnings: Array.isArray(apiPart.extraction_warnings)
      ? apiPart.extraction_warnings
      : [],
    extractionMetadata: apiPart.extraction_metadata ?? null,
    createdAt: apiPart.created_at ?? null,
    updatedAt: apiPart.updated_at ?? null,
  };
}

function clampBackendLimit(limit: number | undefined, fallback: number = 10) {
  const parsed = Number(limit ?? fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(1, Math.min(100, Math.floor(parsed)));
}

function mapPaper(apiPaper: PaperApiModel): Paper {
  return {
    id: apiPaper.id,
    title: stripHtml(apiPaper.title) ?? "Untitled",
    authors: (apiPaper.authors ?? [])
      .map((a) => stripHtml(a) ?? "")
      .filter(Boolean),
    publicationDate: apiPaper.publication_date ?? null,
    journal: stripHtml(apiPaper.journal),
    doi: apiPaper.doi ?? null,
    abstract: stripHtml(apiPaper.abstract),
    // Keep raw markdown/latex content for detailed paper view rendering.
    fullText: apiPaper.full_text ?? null,
    keywords: (apiPaper.keywords ?? [])
      .map((k) => stripHtml(k) ?? "")
      .filter(Boolean),
    source: apiPaper.source,
    sourceId: apiPaper.source_id ?? null,
    url: apiPaper.url ?? null,
    pdfUrl: apiPaper.pdf_url ?? null,
    pdfLocalPath: apiPaper.pdf_local_path ?? null,
    processingStatus: apiPaper.processing_status ?? "pending",
    contentTaskId: apiPaper.content_task_id ?? null,
    processingError: apiPaper.processing_error ?? null,
    summaryRu: apiPaper.summary_ru ?? null,
    analysisRu: apiPaper.analysis_ru ?? null,
    translationRu: apiPaper.translation_ru ?? null,
    parseConfidence: apiPaper.parse_confidence ?? null,
    provenance: apiPaper.provenance ?? {},
    qualityFlags: apiPaper.quality_flags ?? [],
    schemaVersion: apiPaper.schema_version ?? null,
    createdAt: apiPaper.created_at ?? null,
    updatedAt: apiPaper.updated_at ?? null,
  };
}

function mapFullTextSearchResult(apiPaper: PaperApiModel): FullTextSearchResult {
  const paper = mapPaper(apiPaper);
  return {
    ...paper,
    rank: Number(apiPaper.rank ?? 0) || 0,
    snippet: apiPaper.snippet ?? null,
    titleHighlight: apiPaper.title_highlight ?? null,
    abstractHighlight: apiPaper.abstract_highlight ?? null,
    fullTextHighlight: apiPaper.full_text_highlight ?? null,
    hasPdf: Boolean(apiPaper.has_pdf),
    hasFullText: Boolean(apiPaper.has_full_text),
    fullTextIndexed: Boolean(apiPaper.full_text_indexed),
    matchedFields: Array.isArray(apiPaper.matched_fields)
      ? apiPaper.matched_fields
      : [],
  };
}

export async function getPapersList(args: {
  limit: number;
  offset: number;
  source?: PaperListFilters["source"];
}) {
  const { data } = await apiClient.get<PaperApiModel[]>("/papers", {
    params: {
      limit: clampBackendLimit(args.limit),
      offset: args.offset,
      source: args.source && args.source !== "all" ? args.source : undefined,
    },
  });
  return data.map(mapPaper);
}


export async function getRecentPapers(args: {
  limit: number;
  source?: PaperListFilters["source"];
}) {
  const { data } = await apiClient.get<PaperApiModel[]>("/papers/recent", {
    params: {
      limit: clampBackendLimit(args.limit),
      source: args.source && args.source !== "all" ? args.source : undefined,
    },
  });
  return data.map(mapPaper);
}

export async function getPapersCount(source?: PaperSource | "all") {
  const { data } = await apiClient.get<{ total: number }>("/papers/count", {
    params: {
      source: source && source !== "all" ? source : undefined,
    },
  });
  return data.total;
}

export async function searchPapers(filters: PaperSearchFilters) {
  const { data } = await apiClient.post<{
    papers: PaperApiModel[];
    total: number;
    query: string;
    sources: PaperSource[] | string[];
  }>("/papers/search", {
    query: filters.query,
    limit: clampBackendLimit(filters.limit),
    sources: filters.sources,
    full_text_only: filters.fullTextOnly,
  });

  return {
    papers: (data.papers ?? []).map(mapPaper),
    total: data.total ?? 0,
  };
}

export async function getPaperById(paperId: number) {
  const { data } = await apiClient.get<PaperApiModel>(`/papers/id/${paperId}`);
  return mapPaper(data);
}

export function getPaperPdfUrl(paperId: number) {
  return `${apiClient.defaults.baseURL}/papers/id/${paperId}/pdf`;
}

export async function reprocessPaperContent(paperId: number) {
  const { data } = await apiClient.post<{
    paper_id: number;
    task_id: string;
    status: string;
  }>(`/papers/id/${paperId}/reprocess`);
  return data;
}

export async function reprocessAllPapers(args?: {
  limit?: number;
  source?: string;
}) {
  const { data } = await apiClient.post<{
    queued: number;
    task_ids: string[];
  }>(`/papers/reprocess-all`, undefined, {
    params: {
      limit: (() => {
        const parsed = Number(args?.limit ?? 500);
        if (!Number.isFinite(parsed)) return 500;
        return Math.max(1, Math.min(5000, Math.floor(parsed)));
      })(),
      source: args?.source,
    },
  });
  return data;
}

export async function deletePaper(paperId: number) {
  await apiClient.delete(`/papers/id/${paperId}`);
}

export async function parsePapers(args: {
  query: string;
  limit: number;
  source: PaperSource;
  pdfMode: PdfProcessingMode;
}) {
  const { data } = await apiClient.post<{
    message: string;
    task_id: string;
    source: string;
    query: string;
    limit: number;
    pdf_mode: PdfProcessingMode;
  }>(`/papers/parse`, undefined, {
    params: {
      query: args.query,
      limit: clampBackendLimit(args.limit, 50),
      source: args.source,
      pdf_mode: args.pdfMode,
    },
  });

  return data;
}

export async function parseAll(args: {
  limitPerQuery: number;
  source: PaperSource | "all";
  query: string;
  pdfMode: PdfProcessingMode;
}) {
  const { data } = await apiClient.post<{
    message: string;
    task_id: string;
    sources: string[];
    limit_per_query: number;
    pdf_mode: PdfProcessingMode;
    query?: string | null;
  }>(`/papers/parse-all`, undefined, {
    params: {
      limit_per_query: clampBackendLimit(args.limitPerQuery, 50),
      source: args.source,
      query: args.query.trim(),
      pdf_mode: args.pdfMode,
    },
  });

  return data;
}

export async function vectorSearch(filters: VectorSearchFilters) {
  const { data } = await apiClient.post<VectorSearchResponse>(
    "/vector/search",
    {
      query: filters.query,
      limit: clampBackendLimit(filters.limit),
      source:
        filters.source && filters.source !== "all" ? filters.source : undefined,
      date_from: filters.dateFrom,
      date_to: filters.dateTo,
      search_type: filters.searchType,
    },
  );

  return {
    results: data.results ?? [],
    total: data.total ?? 0,
    searchType: data.search_type,
  };
}

export async function getVectorStats() {
  const { data } = await apiClient.get<{
    vector_store?: {
      count?: number;
      available?: boolean;
      collection?: string;
      persist_directory?: string;
    };
    count?: number;
    available?: boolean;
    collection?: string;
    embedding_model?: string | null;
    embedding_dim?: number | null;
    embedding_available?: boolean;
  }>("/vector/stats");

  return {
    count: data.vector_store?.count ?? data.count ?? 0,
    available: data.vector_store?.available ?? data.available ?? false,
    collection: data.vector_store?.collection ?? data.collection,
    embedding_model: data.embedding_model ?? null,
    embedding_dim: data.embedding_dim ?? null,
    embedding_available: data.embedding_available ?? false,
  };
}

export async function rebuildVectorIndex() {
  const { data } = await apiClient.post<{
    message: string;
    indexed: number;
    total: number;
  }>("/vector/rebuild", undefined, { timeout: 10 * 60_000 });

  return data;
}

export type CeleryTaskStatus = {
  task_id: string;
  status:
    | "PENDING"
    | "RECEIVED"
    | "STARTED"
    | "PROGRESS"
    | "RETRY"
    | "FAILURE"
    | "SUCCESS"
    | "REVOKED"
    | "UNKNOWN";
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
    content_queued_count?: number;
    content_skipped_count?: number;
    total_saved?: number;
    total_updated?: number;
    total_duplicates?: number;
    total_content_queued?: number;
    total_content_skipped?: number;
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
  content_queued_count?: number;
  content_skipped_count?: number;
  total_saved?: number;
  total_updated?: number;
  total_duplicates?: number;
  total_content_queued?: number;
  total_content_skipped?: number;
  errors?: string[];
  error?: string;
  name?: string;
  args?: any[];
  kwargs?: Record<string, any>;
};

export async function getCeleryTaskStatus(taskId: string) {
  const { data } = await apiClient.get<CeleryTaskStatus>(
    `/tasks/celery/${taskId}/status`,
  );
  return data;
}

export type SharedParseJob = {
  jobId: string;
  startedAt: number;
  query: string;
  source: PaperSource | "all" | string;
  initialCount: number;
  lastObservedCount: number;
  lastCountChangeAt: number;
  savedCount?: number;
  updatedCount?: number;
  duplicateCount?: number;
  contentQueuedCount?: number;
  contentSkippedCount?: number;
  lastPolledAt?: number;
  status:
    | "in_progress"
    | "completed"
    | "cancelled"
    | "failed"
    | "expired"
    | string;
  celeryStatus?: CeleryTaskStatus;
};

export async function getSharedParseJobs(limit: number = 50) {
  const { data } = await apiClient.get<{ jobs: SharedParseJob[] }>(
    "/tasks/parse-jobs",
    {
      params: { limit },
    },
  );
  return data.jobs ?? [];
}

export async function deleteSharedParseJob(jobId: string) {
  await apiClient.delete(`/tasks/parse-jobs/${jobId}`);
}

export async function revokeCeleryTask(
  taskId: string,
  terminate: boolean = false,
) {
  const { data } = await apiClient.post<{
    task_id: string;
    status: string;
    previous_state?: string;
    terminate?: boolean;
    message?: string;
  }>(`/tasks/celery/${taskId}/revoke`, undefined, {
    params: { terminate },
  });
  return data;
}

export async function deleteCeleryTask(taskId: string) {
  const { data } = await apiClient.delete<{
    task_id: string;
    status: string;
    message?: string;
  }>(`/tasks/celery/${taskId}`);
  return data;
}

export async function stopCeleryQueues(terminate: boolean = false) {
  const { data } = await apiClient.post<{
    status: string;
    revoked: number;
    task_ids: string[];
    purged: number;
    terminate: boolean;
    message?: string;
  }>("/tasks/celery/queues/stop", undefined, {
    params: { terminate },
  });
  return data;
}

export async function startAlloyAnalysis(args: {
  documentId: string;
  text: string;
}) {
  const { data } = await apiClient.post<{
    task_id: string;
    status: string;
    document_id: string;
  }>("/tasks/celery/alloy-analysis", {
    document_id: args.documentId,
    text: args.text,
  });
  return data;
}

export async function startAlloyBatchAnalysis(args: {
  idSpec?: string;
  sources?: string[];
  limit?: number;
}) {
  const { data } = await apiClient.post<{
    task_id: string;
    status: string;
    id_spec?: string | null;
    sources: string[];
    limit: number;
  }>("/tasks/celery/alloy-analysis/batch", {
    id_spec: args.idSpec || null,
    sources: args.sources || [],
    limit: args.limit ?? 100,
  });
  return data;
}

export async function getAlloyAnalysisResults(limit: number = 200) {
  const { data } = await apiClient.get<{
    results: Array<{
      paper_id: number;
      paper_title: string;
      source: string;
      text_length: number;
      chunks_total: number;
      items_count: number;
      warnings_count: number;
      summary_path: string;
      chunk_files: string[];
      extraction?: any;
      error?: string | null;
      updated_at?: string;
    }>;
  }>("/tasks/celery/alloy-analysis/results", {
    params: { limit },
  });
  return data.results || [];
}

export async function getAlloyAnalysisPrompt() {
  const { data } = await apiClient.get<{ prompt: string }>(
    "/tasks/celery/alloy-analysis/prompt",
  );
  return data.prompt || "";
}

export async function saveAlloyAnalysisPrompt(prompt: string) {
  const { data } = await apiClient.put<{ prompt: string; status: string }>(
    "/tasks/celery/alloy-analysis/prompt",
    { prompt },
  );
  return data;
}

// Full-text search API
export async function fullTextSearch(args: {
  query: string;
  limit?: number;
  offset?: number;
  source?: string;
  searchMode?: "plain" | "phrase" | "websearch";
}) {
  const limit = clampBackendLimit(args.limit, 20);
  const offset = Math.max(0, Math.floor(Number(args.offset ?? 0) || 0));
  const { data } = await apiClient.post<{
    papers: PaperApiModel[];
    total: number;
    query: string;
    sources: string[];
    search_mode?: "plain" | "phrase" | "websearch";
    limit?: number;
    offset?: number;
    stats?: FullTextSearchStats;
  }>("/search/fulltext", undefined, {
    params: {
      query: args.query,
      limit,
      offset,
      source: args.source,
      search_mode: args.searchMode || "websearch",
    },
  });

  return {
    papers: (data.papers ?? []).map(mapFullTextSearchResult),
    total: data.total ?? 0,
    query: data.query,
    sources: data.sources ?? [],
    searchMode: data.search_mode ?? args.searchMode ?? "websearch",
    limit: data.limit ?? limit,
    offset: data.offset ?? offset,
    stats: data.stats ?? {
      total_matches: data.total ?? 0,
      avg_relevance: 0,
      max_relevance: 0,
    },
  };
}

export async function getSearchSuggestions(prefix: string, limit: number = 10) {
  const { data } = await apiClient.get<{
    suggestions: string[];
    prefix: string;
    count: number;
  }>("/search/suggest", { params: { prefix, limit } });
  return data.suggestions;
}

export async function searchByKeywords(
  keywords: string[],
  matchAll: boolean = true,
  limit: number = 20,
) {
  const { data } = await apiClient.post<{
    papers: PaperApiModel[];
    total: number;
    keywords: string[];
    match_all: boolean;
  }>("/search/keywords", undefined, {
    params: { keywords, match_all: matchAll, limit },
  });

  return {
    papers: (data.papers ?? []).map(mapPaper),
    total: data.total ?? 0,
  };
}

export async function getSearchStats(
  query: string,
  args?: { source?: string; searchMode?: "plain" | "phrase" | "websearch" },
) {
  const { data } = await apiClient.get<FullTextSearchStats>("/search/stats", {
    params: {
      query,
      source: args?.source,
      search_mode: args?.searchMode ?? "websearch",
    },
  });
  return data;
}

export async function getSearchHighlight(paperId: number, query: string) {
  const { data } = await apiClient.get<{
    paper_id: number;
    title: string;
    abstract: string;
    full_text?: string | null;
  }>(`/search/highlight/${paperId}`, { params: { query } });
  return data;
}

export async function getPaperContentParts(paperId: number) {
  const { data } = await apiClient.get<PaperContentPartApiModel[]>(
    `/papers/id/${paperId}/content-parts`,
  );
  return (data ?? []).map(mapPaperContentPart);
}

export async function regeneratePaperContentPart(
  paperId: number,
  partId: number,
) {
  const { data } = await apiClient.post<PaperContentPartRegenerateResponse>(
    `/papers/id/${paperId}/content-parts/${partId}/regenerate`,
  );
  return data;
}

export async function regeneratePaperMarkdownPages(
  paperId: number,
  pageStart: number,
  pageEnd: number,
) {
  const { data } = await apiClient.post<PaperContentPartRegenerateResponse>(
    `/papers/id/${paperId}/markdown-pages/regenerate`,
    undefined,
    { params: { page_start: pageStart, page_end: pageEnd } },
  );
  return data;
}
