import { useEffect, useRef } from "react";
import * as settingsApi from "../api/settings";
import { useAuthStore } from "../store/authStore";
import { useToast } from "./ui/Toast";

const CHECK_INTERVAL_MS = 60_000;

export default function QwenTokenWatcher() {
  const toast = useToast();
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const lastStatusRef = useRef<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated || !user?.is_admin) return;

    let active = true;
    let timer: number | undefined;

    const check = async () => {
      try {
        const status = await settingsApi.getQwenTokenStatus();
        if (!active) return;

        const key = `${status?.status || "unknown"}:${status?.message || ""}`;
        if (status?.expired && lastStatusRef.current !== key) {
          lastStatusRef.current = key;
          toast.warning(
            status.message || "Токен авторизации нейросети QWEN истёк. Обновите его в технических настройках.",
            15000,
          );
          return;
        }

        if (status?.valid) {
          lastStatusRef.current = "valid";
        }
      } catch {
        // Qwen status check is best-effort. Do not spam users if backend/qwen_service is restarting.
      } finally {
        if (active) {
          timer = window.setTimeout(check, CHECK_INTERVAL_MS);
        }
      }
    };

    check();

    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [isAuthenticated, user?.is_admin, toast]);

  return null;
}
