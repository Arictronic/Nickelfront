import { useAuthStore } from "../../store/authStore";
import { useAuth } from "../../hooks/useAuth";
import { useNavigate } from "react-router-dom";
import { ThemeToggle } from "../../context/ThemeProvider";

export default function Header() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isSessionChecking = useAuthStore((s) => s.isSessionChecking);
  const sessionError = useAuthStore((s) => s.sessionError);
  const { logout } = useAuth();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  let sessionLabel = "Session: none";
  let sessionClass = "inactive";

  if (isSessionChecking) {
    sessionLabel = "Session: checking";
    sessionClass = "checking";
  } else if (sessionError) {
    sessionLabel = "Session: backend unavailable";
    sessionClass = "pending";
  } else if (isAuthenticated) {
    if (user) {
      sessionLabel = "Session: active";
      sessionClass = "active";
    } else {
      sessionLabel = "Session: pending";
      sessionClass = "pending";
    }
  }

  return (
    <header className="header">
      <div className="brand-block">
        <div className="brand-mark">N</div>
        <div>
          <h1>Nickelfront</h1>
        </div>
      </div>

      <div className="header-actions">
        <ThemeToggle />

        <div className={`session-status ${sessionClass}`} title={sessionLabel}>
          <span className="session-dot" />
          <span>{sessionLabel}</span>
        </div>

        <span
          className="user-chip"
          title={user?.email || ""}
        >
          {user?.username || user?.email || (isAuthenticated && sessionError ? "пользователь" : "guest")}
        </span>

        {user || (isAuthenticated && sessionError) ? (
          <button className="btn btn-ghost btn-sm" onClick={handleLogout}>
            {user ? "Выйти" : "Сбросить сессию"}
          </button>
        ) : (
          <button className="btn btn-ghost btn-sm" onClick={() => navigate("/login")}>
            Войти
          </button>
        )}
      </div>
    </header>
  );
}
