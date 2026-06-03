import { apiClient } from "./client";
import type {
  PublicDisplaySettings,
  QwenCacheMaintenanceOptions,
  QwenCacheMaintenanceResponse,
  QwenEventJournalResponse,
  QwenReadinessResponse,
  QwenTestResult,
  QwenTestRunPayload,
  QwenUploadTestResult,
  QwenUploadTestRunPayload,
  QwenTokenStatus,
  SettingsSectionKey,
  SystemSettingsResponse,
} from "../types/settings";

export async function getSystemSettings() {
  const { data } = await apiClient.get<SystemSettingsResponse>("/admin/settings");
  return data;
}

export async function updateSystemSettingsSection<T extends Record<string, any>>(
  section: SettingsSectionKey | string,
  value: T,
) {
  const { data } = await apiClient.patch<{ section: string; value: T }>(
    `/admin/settings/${section}`,
    { value },
  );
  return data;
}

export async function resetSystemSettingsSection(section: SettingsSectionKey | string) {
  const { data } = await apiClient.post<{ section: string; value: Record<string, any> }>(
    `/admin/settings/${section}/reset`,
  );
  return data;
}

export async function getPublicDisplaySettings() {
  const { data } = await apiClient.get<PublicDisplaySettings>("/admin/settings/public-display");
  return data;
}





const QWEN_TOKEN_STATUS_CACHE_MS = 60_000;

type QwenTokenStatusOptions = {

  force?: boolean;
};

let qwenTokenStatusCache: { value: QwenTokenStatus; expiresAt: number } | null = null;
let qwenTokenStatusInFlight: Promise<QwenTokenStatus> | null = null;

export function clearQwenTokenStatusCache(): void {
  qwenTokenStatusCache = null;
  qwenTokenStatusInFlight = null;
}

export async function getQwenTokenStatus(options: QwenTokenStatusOptions = {}): Promise<QwenTokenStatus> {
  const now = Date.now();

  if (!options.force && qwenTokenStatusCache && qwenTokenStatusCache.expiresAt > now) {
    return qwenTokenStatusCache.value;
  }

  if (!options.force && qwenTokenStatusInFlight) {
    return qwenTokenStatusInFlight;
  }

  const request = apiClient
    .get<QwenTokenStatus>("/admin/settings/qwen/token/status", { timeout: 5000 })
    .then(({ data }) => {
      qwenTokenStatusCache = {
        value: data,
        expiresAt: Date.now() + QWEN_TOKEN_STATUS_CACHE_MS,
      };
      return data;
    })
    .finally(() => {
      qwenTokenStatusInFlight = null;
    });

  qwenTokenStatusInFlight = request;
  return request;
}


export async function checkQwenToken() {
  const { data } = await apiClient.post("/admin/settings/qwen/token/check", {}, { timeout: 120000 });
  clearQwenTokenStatusCache();
  return data;
}

export async function updateQwenTokenFromHar(file: File) {
  const formData = new FormData();
  formData.append("har_file", file);
  const { data } = await apiClient.post("/admin/settings/qwen/token/update-from-har", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  clearQwenTokenStatusCache();
  return data;
}

export async function runQwenServiceTest(payload: QwenTestRunPayload) {
  const { data } = await apiClient.post<QwenTestResult>("/admin/settings/qwen/test-run", payload, { timeout: 360000 });
  return data;
}

export async function runQwenUploadTest(payload: QwenUploadTestRunPayload) {
  const { data } = await apiClient.post<QwenUploadTestResult>("/admin/settings/qwen/upload-test-run", payload, { timeout: 420000 });
  return data;
}


export async function getQwenReadiness() {
  const { data } = await apiClient.get<QwenReadinessResponse>("/qwen/readiness", { timeout: 10000 });
  return data;
}

export async function runQwenRuntimeCacheMaintenance(options: QwenCacheMaintenanceOptions = {}) {
  const { data } = await apiClient.post<QwenCacheMaintenanceResponse>("/qwen/cache-maintenance", null, {
    params: {
      dry_run: options.dryRun ?? true,
      prune_file_metadata: options.pruneFileMetadata ?? true,
      prune_session_registry: options.pruneSessionRegistry ?? true,
      file_max_age_days: options.fileMaxAgeDays ?? undefined,
      session_max_age_days: options.sessionMaxAgeDays ?? undefined,
      clear_file_metadata: options.clearFileMetadata ?? false,
      clear_session_registry: options.clearSessionRegistry ?? false,
    },
    timeout: 15000,
  });
  return data;
}

export async function getQwenEventJournal(options: { limit?: number; event?: string; status?: string } = {}) {
  const { data } = await apiClient.get<QwenEventJournalResponse>("/qwen/events", {
    params: {
      limit: options.limit ?? 50,
      event: options.event || undefined,
      status: options.status || undefined,
    },
    timeout: 10000,
  });
  return data;
}

export async function clearQwenEventJournal() {
  const { data } = await apiClient.post<QwenEventJournalResponse>("/qwen/events/clear", null, { timeout: 10000 });
  return data;
}
