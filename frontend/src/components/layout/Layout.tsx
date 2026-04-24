import { Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import Header from "./Header";
import Sidebar from "./Sidebar";
import Footer from "./Footer";

const THEME_STORAGE_KEY = "nickelfront-theme";

export default function Layout() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    return savedTheme === "dark" ? "dark" : "light";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  return (
    <div className="app-shell">
      <div className="app-background" aria-hidden="true">
        <span className="bg-orb orb-one" />
        <span className="bg-orb orb-two" />
        <span className="bg-orb orb-three" />
        <span className="bg-grid" />
        <span className="bg-noise" />
        <span className="bg-bloom bloom-left" />
        <span className="bg-bloom bloom-right" />
        <span className="bg-chromatic chromatic-left" />
        <span className="bg-chromatic chromatic-right" />
      </div>
      <Header theme={theme} onToggleTheme={() => setTheme((current) => (current === "light" ? "dark" : "light"))} />
      <div className="app-body">
        <Sidebar />
        <main className="content">
          <Outlet />
        </main>
      </div>
      <Footer />
    </div>
  );
}
