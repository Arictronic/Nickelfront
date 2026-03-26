import { useAuthStore } from "../../store/authStore";
import { useNavigate } from "react-router-dom";

export default function Header() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  return (
    <header className="header">
      <div className="brand-block">
        <div className="brand-mark">N</div>
        <h1>Nickelfront</h1>
        <p className="header-subtitle">Patent Intelligence Platform</p>
      </div>
      <div className="header-actions">
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
