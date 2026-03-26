import { apiClient } from "./client";
import type { Paper, PaperListFilters, PaperSearchFilters, PaperSource } from "../types/paper";

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

