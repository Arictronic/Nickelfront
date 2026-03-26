export type PaperSource = "CORE" | "arXiv";

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
  createdAt: string | null;
  updatedAt: string | null;
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

