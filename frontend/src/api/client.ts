import axios from "axios";
import { useAuthStore } from "../store/authStore";

const baseURL = import.meta.env.VITE_API_URL || "/api/v1";

export const apiClient = axios.create({
  baseURL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

const refreshClient = axios.create({
  baseURL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
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

    const isAuthRoute = url.includes("/auth/login") || url.includes("/auth/refresh") || url.includes("/auth/register");

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

    if (status === 401 && isAuthRoute) {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("refresh_token");
      window.location.href = "/login";
    }

    return Promise.reject(error);
  }
);
