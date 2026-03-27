import { createContext, useContext, useEffect, useState, ReactNode } from "react";

type Theme = "light" | "dark";

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEY = "nickelfront-theme";

interface ThemeProviderProps {
  children: ReactNode;
  defaultTheme?: Theme;
}

/**
 * Провайдер темы приложения.
 */
export function ThemeProvider({ children, defaultTheme = "light" }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() => {
    // Проверяем сохраненную тему
    const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
    if (saved && (saved === "light" || saved === "dark")) {
      return saved;
    }

    // Проверяем системную тему
    if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      return "dark";
    }

    return defaultTheme;
  });

  useEffect(() => {
    // Применяем тему к документу
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);

    // Сохраняем в localStorage
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
  };

  const toggleTheme = () => {
    setThemeState((prev) => (prev === "light" ? "dark" : "light"));
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

/**
 * Хук для использования темы.
 */
export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}

/**
 * Компонент переключателя темы.
 */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggleTheme } = useTheme();
  const label = theme === "light" ? "Светлая" : "Темная";
  const nextLabel = theme === "light" ? "темную" : "светлую";

  return (
    <button
      className={`btn theme-toggle ${className}`}
      onClick={toggleTheme}
      title={`Переключить на ${nextLabel} тему`}
      type="button"
    >
      <span className="theme-label">Тема</span>
      <span className="theme-value">{label}</span>
    </button>
  );
}

export default ThemeProvider;
