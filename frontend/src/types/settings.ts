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
