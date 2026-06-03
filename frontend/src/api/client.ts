import axios from "axios";
import { useAuthStore } from "../store/authStore";




const apiUrl = String(import.meta.env.VITE_API_URL || "").trim();
const baseURL = apiUrl || "/api/v1";

function serializeParams(params: Record<string, unknown>): string {
  const searchParams = new URLSearchParams();

  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;

    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== "") {
          searchParams.append(key, String(item));
        }
      });
      return;
    }

    searchParams.append(key, String(value));
  });

  return searchParams.toString();
}


function extractApiErrorMessage(payload: any): string | null {
  const detail = payload?.detail ?? payload?.message ?? payload?.error ?? payload?.details;

  if (typeof detail === "string" && detail.trim()) return detail;

  if (detail && typeof detail === "object") {
    const nested = detail.message ?? detail.error ?? detail.reason ?? detail.detail?.message;
    const code = detail.code ?? detail.error_code ?? detail.status;
    if (typeof nested === "string" && nested.trim()) {
      return code ? `${nested} (${code})` : nested;
    }
  }

  const direct = payload?.message ?? payload?.error;
  if (typeof direct === "string" && direct.trim()) return direct;

  return null;
}

export const apiClient = axios.create({
  baseURL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
  paramsSerializer: {
    serialize: serializeParams,
  },
});

const refreshClient = axios.create({
  baseURL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
  paramsSerializer: {
    serialize: serializeParams,
  },
});

let refreshPromise: Promise<{ access_token: string; refresh_token: string } | null> | null = null;

function clearAuthAndRedirect(): void {
  useAuthStore.getState().logout();
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}


apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("auth_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);


apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = (error.config || {}) as any;
    const status = error.response?.status;
    const url: string = originalRequest.url || "";

    const isLoginRoute = url.includes("/auth/login");
    const isRegisterRoute = url.includes("/auth/register");
    const isRefreshRoute = url.includes("/auth/refresh");
    const isAuthRoute = isLoginRoute || isRegisterRoute || isRefreshRoute;

    if (status === 401 && !originalRequest._retry && !isAuthRoute) {
      const refreshToken = localStorage.getItem("refresh_token");
      if (!refreshToken) {
        clearAuthAndRedirect();
        return Promise.reject(error);
      }

      originalRequest._retry = true;

      if (!refreshPromise) {
        refreshPromise = refreshClient
          .post("/auth/refresh", { refresh_token: refreshToken })
          .then((res) => res.data)
          .catch(() => null)
          .finally(() => {
            refreshPromise = null;
          });
      }

      const data = await refreshPromise;
      if (!data?.access_token || !data?.refresh_token) {
        clearAuthAndRedirect();
        return Promise.reject(error);
      }

      localStorage.setItem("auth_token", data.access_token);
      localStorage.setItem("refresh_token", data.refresh_token);
      useAuthStore.getState().setToken(data.access_token);
      useAuthStore.getState().setRefreshToken(data.refresh_token);
      useAuthStore.getState().setSessionError(null);


      refreshClient
        .get("/auth/me", {
          headers: { Authorization: `Bearer ${data.access_token}` },
        })
        .then((profile) => {
          if (profile?.data) {
            useAuthStore.getState().setUser(profile.data);
          }
        })
        .catch(() => {});

      originalRequest.headers = originalRequest.headers || {};
      originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
      return apiClient(originalRequest);
    }


    if (status === 401 && isRefreshRoute) {
      clearAuthAndRedirect();
    }

    const payload = error.response?.data;
    const apiMessage = extractApiErrorMessage(payload);
    if (apiMessage) {
      error.message = apiMessage;
    }

    return Promise.reject(error);
  }
);

function normalizeRootUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  try {
    if (/^https?:\/\//i.test(trimmed)) {
      return new URL(trimmed).origin;
    }

    if (typeof window !== "undefined" && trimmed.startsWith("/")) {
      return window.location.origin;
    }
  } catch {
    return null;
  }

  return null;
}

export function getBackendRootUrl(): string {
  const envCandidates = [
    String(import.meta.env.VITE_BACKEND_ROOT_URL || ""),
    String(import.meta.env.VITE_PROXY_TARGET || ""),
    String(import.meta.env.VITE_API_URL || ""),
  ];

  for (const candidate of envCandidates) {
    const normalized = normalizeRootUrl(candidate);
    if (normalized) return normalized;
  }

  const configuredBase = normalizeRootUrl(String(apiClient.defaults.baseURL || ""));
  if (configuredBase) return configuredBase;

  const apiPort = String(import.meta.env.API_PORT || import.meta.env.VITE_API_PORT || "").trim();
  if (/^\d+$/.test(apiPort)) {
    return `http://127.0.0.1:${apiPort}`;
  }

  return "http://127.0.0.1:8001";
}
