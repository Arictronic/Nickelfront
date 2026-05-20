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

  let sessionTitle = "Нет сессии";
  let dotColor = "#555";

  if (isSessionChecking) {
    sessionTitle = "Проверка...";
    dotColor = "#f59e0b";
  } else if (isAuthenticated && user) {
    sessionTitle = "Сессия активна";
    dotColor = "#22c55e";
  } else if (isAuthenticated) {
    sessionTitle = "Ожидание";
    dotColor = "#f59e0b";
  }

  return (
    <header className="header">
      <div className="brand-block">
        <div className="brand-mark">N</div>
        <h1>Nickelfront</h1>
      </div>
      <div className="header-actions">
        <ThemeToggle />

        {/* Только точка с tooltip вместо текста */}
        <div
          title={sessionTitle}
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: dotColor,
            boxShadow: `0 0 6px ${dotColor}`,
            animation: "pulse-dot 2.4s ease-in-out infinite",
            flexShrink: 0,
            cursor: "default",
          }}
        />

        {user && (
          <span className="user-chip">
            {user.username || user.email}
          </span>
        )}

        {user ? (
          <button className="btn btn-ghost" onClick={handleLogout}>
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