import { create } from "zustand";
import type { User } from "../types/user";

interface AuthState {
  user: User | null;
  token: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isSessionChecking: boolean;
  login: (user: User, token: string, refreshToken: string) => void;
  logout: () => void;
  setToken: (token: string) => void;
  setRefreshToken: (token: string) => void;
  setUser: (user: User | null) => void;
  setAuthenticated: (value: boolean) => void;
  setSessionChecking: (value: boolean) => void;
  setLoading: (loading: boolean) => void;
}

const getStoredToken = (): string | null => {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("auth_token");
};

const getStoredRefreshToken = (): string | null => {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("refresh_token");
};

const setStoredToken = (token: string | null): void => {
  if (typeof window === "undefined") return;
  if (token) {
    localStorage.setItem("auth_token", token);
  } else {
    localStorage.removeItem("auth_token");
  }
};

const setStoredRefreshToken = (token: string | null): void => {
  if (typeof window === "undefined") return;
  if (token) {
    localStorage.setItem("refresh_token", token);
  } else {
    localStorage.removeItem("refresh_token");
  }
};

const hasStoredAuth = () => !!getStoredToken() || !!getStoredRefreshToken();

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: getStoredToken(),
  refreshToken: getStoredRefreshToken(),
  isAuthenticated: hasStoredAuth(),
  isLoading: false,
  isSessionChecking: false,
  login: (user, token, refreshToken) => {
    setStoredToken(token);
    setStoredRefreshToken(refreshToken);
    set({ user, token, refreshToken, isAuthenticated: true, isLoading: false });
  },
  logout: () => {
    setStoredToken(null);
    setStoredRefreshToken(null);
    set({ user: null, token: null, refreshToken: null, isAuthenticated: false, isLoading: false });
  },
  setToken: (token) => {
    setStoredToken(token);
    set({ token, isAuthenticated: !!token || !!getStoredRefreshToken() });
  },
  setRefreshToken: (token) => {
    setStoredRefreshToken(token);
    set({ refreshToken: token, isAuthenticated: !!token || !!getStoredToken() });
  },
  setUser: (user) => set({ user }),
  setAuthenticated: (value) => set({ isAuthenticated: value }),
  setSessionChecking: (value) => set({ isSessionChecking: value }),
  setLoading: (loading) => set({ isLoading: loading }),
}));
