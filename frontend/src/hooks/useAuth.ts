import { useAuthStore } from "../store/authStore";
import * as authApi from "../api/auth";

export function useAuth() {
  const loginStore = useAuthStore((s) => s.login);
  const logout = useAuthStore((s) => s.logout);

  const login = async (email: string, password: string) => {
    const user = await authApi.login(email, password);
    loginStore(user);
  };

  const register = async (email: string, password: string) => {
    await authApi.register(email, password);
  };

  return { login, register, logout };
}
