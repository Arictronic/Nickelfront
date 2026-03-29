import { Navigate, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

export default function Landing() {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "24px",
        background: "linear-gradient(180deg, #0b1220 0%, #111827 100%)",
      }}
    >
      <section
        style={{
          width: "100%",
          maxWidth: "680px",
          border: "1px solid rgba(255,255,255,0.14)",
          borderRadius: "16px",
          padding: "28px",
          background: "rgba(17, 24, 39, 0.78)",
          color: "#e5e7eb",
          boxShadow: "0 18px 40px rgba(0,0,0,0.35)",
        }}
      >
        <h1 style={{ margin: "0 0 10px", fontSize: "28px", lineHeight: 1.2 }}>Nickelfront</h1>
        <p style={{ margin: "0 0 18px", color: "#9ca3af" }}>
          Платформа для работы с научными статьями: парсинг, анализ и поиск.
        </p>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          <button
            className="btn btn-primary"
            onClick={() => navigate("/login")}
            style={{ minWidth: "130px" }}
          >
            Войти
          </button>
          <button
            className="btn"
            onClick={() => navigate("/register")}
            style={{ minWidth: "130px" }}
          >
            Регистрация
          </button>
        </div>
      </section>
    </div>
  );
}
