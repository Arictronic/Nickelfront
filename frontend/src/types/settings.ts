import type { PaperSource } from "./paper";

export type SettingsSectionKey = "parser" | "pdf_markdown" | "qwen" | "workers" | "system";

export type ParserPostprocessSettings = {
  download_pdf: boolean;
  extract_pdf_text: boolean;
  qwen_markdown: boolean;
  qwen_ru_analysis: boolean;
  qwen_keywords: boolean;
  embedding: boolean;
};

export type ParserSettings = {
  enabled: boolean;
  default_limit: number;
  max_limit: number;
  subprocess_timeout_seconds: number;
  retry_count: number;
  retry_delay_seconds: number;
  max_parallel_parse_jobs: number;
  enabled_sources: Record<PaperSource | string, boolean>;
  source_limits: Record<PaperSource | string, number>;
  postprocess: ParserPostprocessSettings;
};

export type PdfMarkdownSettings = {
  pages_per_request: number;
  page_chars: number;
  save_raw_parts: boolean;
  save_markdown_parts: boolean;
  normalize_math: boolean;
  show_extraction_diagnostics: boolean;
  parser_mode: "auto" | "ai" | string;
  ocr_mode: "auto" | "force" | "off" | string;
  ai_mode: "off" | "auto" | "force" | string;
  force_strategy: "" | "simple" | "layout" | "columns" | "ocr" | "ai" | string;
  extraction_mode: "auto" | "layout" | "columns" | "simple" | "ocr" | "ai" | string;
  ocr_engine: "auto" | "tesseract" | "paddle" | "surya" | "ocrmypdf" | string;
  ai_provider: string;
  ai_model: string;
  ai_endpoint: string;
  ai_render_dpi: number;
  ai_page_image_format: "png" | "jpeg" | "jpg" | "webp" | string;
  ai_timeout_sec: number;
  detect_columns: boolean;
  extract_tables: boolean;
  remove_headers_footers: boolean;
  merge_hyphenated_words: boolean;
  mark_formula_candidates: boolean;
  ocr_enabled: boolean;
  ocr_dpi: number;
  ocr_languages: string;
  min_text_chars: number;
  max_page_chars: number;
};

export type QwenSettings = {
  markdown_enabled: boolean;
  ru_analysis_enabled: boolean;
  keywords_enabled: boolean;
  request_timeout_seconds: number;
  model: string;
  token_configured: boolean;
};

export type SystemSettings = {
  parser: ParserSettings;
  pdf_markdown: PdfMarkdownSettings;
  qwen: QwenSettings;
  [key: string]: any;
};

export type SystemSettingsSchema = {
  sections: Array<{ key: SettingsSectionKey | string; title: string; editable: boolean }>;
  available_sources: Array<PaperSource | string>;
  readonly?: Record<string, any>;
};

export type SystemSettingsResponse = {
  settings: SystemSettings;
  schema: SystemSettingsSchema;
};

export type PublicDisplaySettings = {
  show_extraction_diagnostics: boolean;
};

export type QwenTokenStatus = {
  status: "valid" | "expired" | "missing" | "invalid" | "rate_limited" | "service_unavailable" | "unknown" | string;
  valid: boolean;
  expired: boolean;
  rate_limited?: boolean;
  token_configured: boolean;
  message: string;
  model?: string | null;
  user?: Record<string, unknown> | null;
  checked_by?: string | null;
  service_available?: boolean | null;
  active_sessions?: number | null;
  max_active_sessions?: number | null;
  provider_max_concurrent_requests?: number | null;
};

export type QwenHarUpdateResponse = {
  updated: boolean;
  message: string;
  qwen_status: QwenTokenStatus;
  token_source?: {
    source?: string;
    url?: string;
    started_at?: string;
    token_preview?: string;
    candidates_count?: number;
    unique_tokens_count?: number;
  };
};

export type QwenTestChatResult = {
  chat: number;
  started_at_sec: number;
  finished_at_sec: number;
  duration_sec: number;
  session_id: string;
  error: string;
  response_start: string;
};

export type QwenTestResult = {
  ok: boolean;
  status: "ok" | "partial" | "warning" | "error" | string;
  message: string;
  service_url: string;
  message_used?: string;
  chat_count: number;
  successful_count: number;
  failed_count: number;
  looks_parallel: boolean;
  start_spread_sec?: number | null;
  finished_spread_sec?: number | null;
  duration_spread_sec?: number | null;
  rate_limited_count?: number;
  provider_limited?: boolean;
  service_health?: Record<string, unknown>;
  token_status?: Record<string, unknown>;
  results: QwenTestChatResult[];
};

export type QwenTestRunPayload = {
  chat_count: number;
  message: string;
};
