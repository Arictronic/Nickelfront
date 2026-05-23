import { apiClient } from "./client";
import type { SettingsSectionKey, SystemSettingsResponse } from "../types/settings";

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
