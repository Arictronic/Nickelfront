import { useAuthStore } from "../../store/authStore";
import { useAuth } from "../../hooks/useAuth";
import { useNavigate } from "react-router-dom";
import { ThemeToggle } from "../../context/ThemeProvider";

export default function Header() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isSessionChecking = useAuthStore((s) => s.isSessionChecking);
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
        <h1>Nickelfront</h1>
        <p className="header-subtitle">Patent Intelligence Platform</p>
      </div>
      <div className="header-actions">
        <ThemeToggle />
        <div className={`session-status ${sessionClass}`} title={sessionLabel}>
          <span className="session-dot" />
          <span>{sessionLabel}</span>
        </div>
        <span className="user-chip">{user?.username || user?.email || "guest@local"}</span>
        {user ? (
          <button className="btn btn-ghost" onClick={handleLogout}>
            ?????
          </button>
        ) : (
          <button className="btn btn-ghost" onClick={() => navigate("/login")}>?????</button>
        )}
      </div>
    </header>
  );
}
