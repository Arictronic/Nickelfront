import { create } from "zustand";
import type { User } from "../types/user";

const mockDesignReviewUser: User = {
  email: "design-review@local.test",
};

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  login: (user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: mockDesignReviewUser,
  isAuthenticated: true,
  login: (user) => set({ user, isAuthenticated: true }),
  logout: () => set({ user: null, isAuthenticated: false }),
}));
