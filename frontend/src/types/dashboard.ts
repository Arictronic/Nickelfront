import type { PaperSource } from "./paper";
import type { ParseJob } from "../utils/parseJobs";

export type DashboardStatusLevel = "online" | "offline" | "warning" | "unknown";
export type DashboardDiagnosticLevel = "success" | "info" | "warning" | "error";

export interface DashboardCounts {
  totalPapers: number;
  todayPapers: number;
  withAbstract: number;
  withFullText: number;
  withPdf: number;
  withEmbeddings: number;
  ragReady: number;
  metadataReady: number;
  qwenReady: number;
  withContentParts: number;
  contentReady: number;
  ragCandidates: number;
  vectorIndexed: number;
  vectorIndexRecords: number;
  ragIndexed: number;
  vectorIdsStatus: "verified" | "unknown";
  ragIdsStatus: "verified" | "unknown";
  processingErrors: number;
  contentQueued: number;
}

export interface DashboardPipeline {
  metadataPercent: number;
  abstractPercent: number;
  fullTextPercent: number;
  pdfPercent: number;
  contentPartsPercent: number;
  contentReadyPercent: number;
  embeddingPercent: number;
  vectorPercent: number;
  ragPercent: number;
  qwenPercent: number;
  qualityPercent: number;
}

export interface DashboardServiceStatus {
  status: DashboardStatusLevel;
  label: string;
  workers?: number;
  active?: number;
  queued?: number;
  reserved?: number;
  scheduled?: number;
  count?: number;
  indexed?: number;
  memory?: string | null;
  model?: string | null;
  path?: string | null;
  collection?: string | null;
  index_status?: string | null;
  ids_status?: "verified" | "unknown" | null;
  candidates?: number;
  ready?: number;
  gap?: number | null;
  reason?: string | null;
  error?: string | null;
  available?: boolean;
  has_token?: boolean | null;
}

export interface DashboardJobsSummary {
  active: number;
  queued: number;
  failedRecent: number;
}

export interface DashboardSourceStatus {
  name: PaperSource | string;
  kind: "API" | "HTML" | string;
  enabled: boolean;
  limit: number;
  papersCount: number;
  addedToday: number;
  withFullText: number;
  withEmbeddings: number;
  errors: number;
  successRate: number | null;
  errorRate: number | null;
  lastDurationSec: number | null;
  lastStatus: string | null;
  lastError: string | null;
  lastRunAt: number | string | null;
}

export interface DashboardDiagnostic {
  level: DashboardDiagnosticLevel;
  title: string;
  message: string;
  actionLabel?: string | null;
  actionTo?: string | null;
}

export type DashboardActionName =
  | "process_pdf_backlog"
  | "retry_failed_content"
  | "rebuild_embeddings"
  | "reindex_vector_store"
  | "rebuild_vector_store_full"
  | "rebuild_rag_index"
  | "rerun_source";

export interface DashboardRecommendedAction {
  kind: DashboardDiagnosticLevel;
  title: string;
  description: string;
  actionLabel: string;
  actionTo: string;
  actionName?: DashboardActionName | null;
  actionPayload?: DashboardActionPayload | null;
}

export interface DashboardActionPayload {
  limit?: number;
  source?: string | null;
  query?: string | null;
  pdf_mode?: string | null;
}

export interface DashboardActionResult {
  action: DashboardActionName | string;
  title: string;
  taskId: string;
  status: string;
  source?: string | null;
  query?: string | null;
  jobType?: string | null;
  parseAdmission?: Record<string, unknown> | null;
}

export interface DashboardOverview {
  generatedAt: string;
  counts: DashboardCounts;
  pipeline: DashboardPipeline;
  services: Record<string, DashboardServiceStatus>;
  jobs: DashboardJobsSummary;
  sources: DashboardSourceStatus[];
  diagnostics: DashboardDiagnostic[];
  recommendedActions: DashboardRecommendedAction[];
}

export interface DashboardJobsResponse {
  jobs: ParseJob[];
  summary: DashboardJobsSummary;
}

export interface DashboardLoadError {
  key: string;
  label: string;
  message: string;
}
