import { useAuthStore } from "../../store/authStore";
import { useNavigate } from "react-router-dom";

type HeaderProps = {
  theme: "light" | "dark";
  onToggleTheme: () => void;
};

export default function Header({ theme, onToggleTheme }: HeaderProps) {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  return (
    <header className="header">
      <div className="brand-block">
        <div className="brand-mark">N</div>
        <div>
          <h1>Nickelfront</h1>
          <p className="header-subtitle">Materials Research Intelligence Platform</p>
        </div>
      </div>
      <div className="header-actions">
        <div className="nav-glow" aria-hidden="true" />
        <button className="theme-toggle" type="button" onClick={onToggleTheme} aria-label="Переключить тему">
          <span className="theme-toggle-icon" aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
          <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
        </button>
        <span className="user-chip">{user?.email ?? "guest@local"}</span>
        {user ? (
          <button
            className="btn btn-ghost"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            Выйти
          </button>
        ) : (
          <button className="btn btn-ghost" onClick={() => navigate("/login")}>
            Войти
          </button>
        )}
      </div>
    </header>
  );
}
