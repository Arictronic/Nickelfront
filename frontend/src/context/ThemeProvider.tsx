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

  return (
    <button
      className={`btn ${className}`}
      onClick={toggleTheme}
      title={`Переключить на ${theme === "light" ? "темную" : "светлую"} тему`}
      style={{
        background: "transparent",
        border: "1px solid currentColor",
        padding: "8px 12px",
        borderRadius: 8,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      {theme === "light" ? (
        <>
          <span>🌙</span>
          <span style={{ fontSize: 13 }}>Темная</span>
        </>
      ) : (
        <>
          <span>☀️</span>
          <span style={{ fontSize: 13 }}>Светлая</span>
        </>
      )}
    </button>
  );
}

export default ThemeProvider;
