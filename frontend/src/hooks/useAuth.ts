import { useAuthStore } from "../store/authStore";
import * as authApi from "../api/auth";
import type { LoginRequest, RegisterRequest } from "../types/user";

export function useAuth() {
  const { login: loginStore, logout: logoutStore, setToken, setRefreshToken, setLoading } = useAuthStore();

  const login = async (data: LoginRequest) => {
    setLoading(true);
    try {
      const response = await authApi.login(data);
      // Сначала сохраняем токен
      setToken(response.access_token);
      setRefreshToken(response.refresh_token);
      // Затем получаем данные пользователя (теперь с токеном)
      const user = await authApi.getCurrentUser();
      loginStore(user, response.access_token, response.refresh_token);
      return user;
    } finally {
      setLoading(false);
    }
  };

  const register = async (data: RegisterRequest) => {
    setLoading(true);
    try {
      const user = await authApi.register(data);
      return user;
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await authApi.logout();
    } finally {
      logoutStore();
    }
  };

  return { login, register, logout };
}
