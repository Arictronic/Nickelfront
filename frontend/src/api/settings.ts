import { apiClient } from "./client";
import type { PublicDisplaySettings, SettingsSectionKey, SystemSettingsResponse } from "../types/settings";

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

export async function getQwenTokenStatus() {
  const { data } = await apiClient.get("/admin/settings/qwen/token/status");
  return data;
}

export async function checkQwenToken() {
  const { data } = await apiClient.post("/admin/settings/qwen/token/check");
  return data;
}

export async function updateQwenTokenFromHar(file: File) {
  const formData = new FormData();
  formData.append("har_file", file);
  const { data } = await apiClient.post("/admin/settings/qwen/token/update-from-har", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return data;
}
