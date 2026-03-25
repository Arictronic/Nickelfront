export type PatentStatus = "active" | "expired";

export interface Patent {
  id: number;
  patentNumber: string;
  title: string;
  applicant: string;
  publicationDate: string;
  filingDate: string;
  category: string;
  country: string;
  status: PatentStatus;
  abstract: string;
  claims: string;
  pdfUrl?: string;
}

export interface PatentFilters {
  search: string;
  category: string;
  country: string;
  status: "" | PatentStatus;
  dateFrom: string;
  dateTo: string;
}
