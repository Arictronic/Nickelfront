import axios from "axios";
import { useAuthStore } from "../store/authStore";

// Определяем базовый URL API
// - Если задан VITE_API_URL (полный URL), используем его
// - Иначе используем относительный путь (для работы через proxy на сервере)
const apiUrl = import.meta.env.VITE_API_URL;
const baseURL = apiUrl ? apiUrl : "/api/v1";

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

// Add auth header
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

// Handle 401 with refresh token rotation
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
        localStorage.removeItem("auth_token");
        localStorage.removeItem("refresh_token");
        window.location.href = "/login";
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
        localStorage.removeItem("auth_token");
        localStorage.removeItem("refresh_token");
        window.location.href = "/login";
        return Promise.reject(error);
      }

      localStorage.setItem("auth_token", data.access_token);
      localStorage.setItem("refresh_token", data.refresh_token);
      useAuthStore.getState().setToken(data.access_token);
      useAuthStore.getState().setRefreshToken(data.refresh_token);

      // Background profile refresh to avoid UI flicker
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

    // Keep login/register errors inside UI form (no forced page reload).
    if (status === 401 && isRefreshRoute) {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("refresh_token");
      window.location.href = "/login";
    }

    return Promise.reject(error);
  }
);

export function getBackendRootUrl(): string {
  const configuredBase = String(apiClient.defaults.baseURL || "");

  try {
    if (/^https?:\/\//i.test(configuredBase)) {
      return new URL(configuredBase).origin;
    }
  } catch {
    // Fallback below.
  }

  // In local Vite mode apiClient usually uses relative /api/v1 through proxy.
  // Backend Swagger is not under /api, so point directly to the local FastAPI server.
  return "http://localhost:8001";
}
