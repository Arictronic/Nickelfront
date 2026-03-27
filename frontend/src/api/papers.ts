import { apiClient } from "./client";
import type { Paper, PaperListFilters, PaperSearchFilters, PaperSource } from "../types/paper";
import type { VectorSearchFilters, VectorSearchResponse } from "../types/paper";

type PaperApiModel = {
  id: number;
  title: string;
  authors: string[];
  publication_date: string | null;
  journal: string | null;
  doi: string | null;
  abstract: string | null;
  full_text: string | null;
  keywords: string[];
  source: PaperSource | string;
  source_id: string | null;
  url: string | null;
  created_at: string | null;
  updated_at: string | null;
};

function mapPaper(apiPaper: PaperApiModel): Paper {
  return {
    id: apiPaper.id,
    title: apiPaper.title,
    authors: apiPaper.authors ?? [],
    publicationDate: apiPaper.publication_date ?? null,
    journal: apiPaper.journal ?? null,
    doi: apiPaper.doi ?? null,
    abstract: apiPaper.abstract ?? null,
    fullText: apiPaper.full_text ?? null,
    keywords: apiPaper.keywords ?? [],
    source: apiPaper.source,
    sourceId: apiPaper.source_id ?? null,
    url: apiPaper.url ?? null,
    createdAt: apiPaper.created_at ?? null,
    updatedAt: apiPaper.updated_at ?? null,
  };
}

export async function getPapersList(args: {
  limit: number;
  offset: number;
  source?: PaperListFilters["source"];
}) {
  const { data } = await apiClient.get<PaperApiModel[]>("/papers", {
    params: {
      limit: args.limit,
      offset: args.offset,
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
    limit: filters.limit,
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

export async function deletePaper(paperId: number) {
  await apiClient.delete(`/papers/id/${paperId}`);
}

export async function parsePapers(args: { query: string; limit: number; source: "CORE" | "arXiv" }) {
  const { data } = await apiClient.post<{
    message: string;
    task_id: string;
    source: string;
    query: string;
    limit: number;
  }>(`/papers/parse`, undefined, {
    params: {
      query: args.query,
      limit: args.limit,
      source: args.source,
    },
  });

  return data;
}

export async function parseAll(args: { limitPerQuery: number; source: "CORE" | "arXiv" | "all" }) {
  const { data } = await apiClient.post<{
    message: string;
    task_id: string;
    sources: string[];
    limit_per_query: number;
  }>(`/papers/parse-all`, undefined, {
    params: {
      limit_per_query: args.limitPerQuery,
      source: args.source,
    },
  });

  return data;
}

export async function vectorSearch(filters: VectorSearchFilters) {
  const { data } = await apiClient.post<VectorSearchResponse>("/vector/search", {
    query: filters.query,
    limit: filters.limit,
    source: filters.source && filters.source !== "all" ? filters.source : undefined,
    date_from: filters.dateFrom,
    date_to: filters.dateTo,
    search_type: filters.searchType,
  });

  return {
    results: data.results ?? [],
    total: data.total ?? 0,
    searchType: data.search_type,
  };
}

export async function getVectorStats() {
  const { data } = await apiClient.get<{
    count: number;
    available: boolean;
    collection?: string;
    embedding_model?: string | null;
    embedding_dim?: number | null;
    embedding_available?: boolean;
  }>("/vector/stats");

  return data;
}

export async function rebuildVectorIndex() {
  const { data } = await apiClient.post<{
    message: string;
    indexed: number;
    total: number;
  }>("/vector/rebuild");

  return data;
}

export type CeleryTaskStatus = {
  task_id: string;
  status: "PENDING" | "STARTED" | "RETRY" | "FAILURE" | "SUCCESS" | "REVOKED";
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
};

export async function getCeleryTaskStatus(taskId: string) {
  const { data } = await apiClient.get<CeleryTaskStatus>(`/tasks/celery/${taskId}/status`);
  return data;
}

export async function revokeCeleryTask(taskId: string, terminate: boolean = false) {
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

// Full-text search API
export async function fullTextSearch(args: {
  query: string;
  limit?: number;
  offset?: number;
  source?: string;
  searchMode?: "plain" | "phrase" | "websearch";
}) {
  const { data } = await apiClient.post<{
    papers: PaperApiModel[];
    total: number;
    query: string;
    sources: string[];
  }>("/search/fulltext", undefined, {
    params: {
      query: args.query,
      limit: args.limit || 20,
      offset: args.offset || 0,
      source: args.source,
      search_mode: args.searchMode || "websearch",
    },
  });

  return {
    papers: (data.papers ?? []).map(mapPaper),
    total: data.total ?? 0,
    query: data.query,
  };
}

export async function getSearchSuggestions(prefix: string, limit: number = 10) {
  const { data } = await apiClient.get<{ suggestions: string[]; prefix: string; count: number }>(
    "/search/suggest",
    { params: { prefix, limit } }
  );
  return data.suggestions;
}

export async function searchByKeywords(keywords: string[], matchAll: boolean = true, limit: number = 20) {
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

export async function getSearchStats(query: string) {
  const { data } = await apiClient.get<{
    total_matches: number;
    avg_relevance: number;
    max_relevance: number;
  }>("/search/stats", { params: { query } });
  return data;
}

export async function getSearchHighlight(paperId: number, query: string) {
  const { data } = await apiClient.get<{
    paper_id: number;
    title: string;
    abstract: string;
  }>(`/search/highlight/${paperId}`, { params: { query } });
  return data;
}

