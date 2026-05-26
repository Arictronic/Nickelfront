import { apiClient } from "./client";
import type {
  PublicDisplaySettings,
  QwenTestResult,
  QwenTestRunPayload,
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


// Lightweight client-side cache for Qwen token status.
// This endpoint is used by global UI status indicators and settings pages,
// so without dedupe several mounted components can poll the backend at once.
const QWEN_TOKEN_STATUS_CACHE_MS = 60_000;

type QwenTokenStatusOptions = {
  /** Force a real request, for example after manual token update/check. */
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

  qwenTokenStatusInFlight = apiClient
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

  return qwenTokenStatusInFlight;
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
