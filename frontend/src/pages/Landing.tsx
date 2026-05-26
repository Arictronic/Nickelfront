import { Navigate, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

const FEATURES = [
  {
    icon: "📄",
    title: "Парсинг статей",
    desc: "Автоматический сбор научных публикаций из открытых источников с извлечением полного текста.",
  },
  {
    icon: "🔍",
    title: "Семантический поиск",
    desc: "Векторный и полнотекстовый поиск по базе статей с ранжированием по релевантности.",
  },
  {
    icon: "⚗️",
    title: "Анализ сплавов",
    desc: "AI-анализ публикаций для извлечения данных о составах и свойствах материалов.",
  },
  {
    icon: "📊",
    title: "Аналитика и метрики",
    desc: "Графики, KPI, качество данных и статистика по всей базе в режиме реального времени.",
  },
];

export default function Landing() {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="landing-root">
      <div className="landing-bg" aria-hidden="true">
        <div className="landing-bg-orb landing-bg-orb-1" />
        <div className="landing-bg-orb landing-bg-orb-2" />
      </div>

      <header className="landing-nav">
        <div className="brand-block" style={{ textDecoration: "none" }}>
          <div className="brand-mark" style={{ width: 36, height: 36, fontSize: 18 }}>N</div>
          <span style={{ fontWeight: 800, fontSize: 20, color: "#fff", letterSpacing: "-0.3px" }}>
            Nickelfront
          </span>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn landing-btn-outline" onClick={() => navigate("/register")}>
            Регистрация
          </button>
          <button className="btn landing-btn-primary" onClick={() => navigate("/login")}>
            Войти
          </button>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-badge">Платформа для научных исследований</div>
          <h1 className="landing-h1">
            Управляйте научными<br />
            <span className="landing-accent">публикациями</span> умнее
          </h1>
          <p className="landing-lead">
            Nickelfront — единая система для парсинга, хранения, поиска и AI-анализа
            научных статей по материаловедению и сплавам.
          </p>
          <div className="landing-cta">
            <button
              className="btn landing-btn-primary landing-btn-lg"
              onClick={() => navigate("/login")}
            >
              Начать работу
            </button>
            <button
              className="btn landing-btn-outline landing-btn-lg"
              onClick={() => navigate("/register")}
            >
              Создать аккаунт
            </button>
          </div>
        </section>

        <section className="landing-features">
          {FEATURES.map((f) => (
            <div key={f.title} className="landing-feature-card">
              <div className="landing-feature-icon">{f.icon}</div>
              <h3 className="landing-feature-title">{f.title}</h3>
              <p className="landing-feature-desc">{f.desc}</p>
            </div>
          ))}
        </section>
      </main>

      <footer className="landing-footer">
        <span>© Nickelfront</span>
      </footer>

      <style>{`
        .landing-root {
          min-height: 100vh;
          background: #070d1a;
          color: #e8edf5;
          display: flex;
          flex-direction: column;
          position: relative;
          overflow-x: hidden;
          font-family: var(--font-body, "Manrope", sans-serif);
        }
        .landing-bg {
          position: fixed;
          inset: 0;
          pointer-events: none;
          z-index: 0;
        }
        .landing-bg-orb {
          position: absolute;
          border-radius: 50%;
          filter: blur(96px);
          opacity: 0.18;
        }
        .landing-bg-orb-1 {
          width: 640px; height: 640px;
          background: #3d5cf5;
          top: -160px; left: -120px;
        }
        .landing-bg-orb-2 {
          width: 480px; height: 480px;
          background: #7c3aed;
          bottom: 60px; right: -80px;
        }
        .landing-nav {
          position: relative;
          z-index: 10;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 20px 48px;
          border-bottom: 1px solid rgba(255,255,255,0.07);
        }
        .landing-hero {
          position: relative;
          z-index: 10;
          text-align: center;
          padding: 100px 24px 80px;
          max-width: 820px;
          margin: 0 auto;
        }
        .landing-badge {
          display: inline-block;
          border: 1px solid rgba(61, 92, 245, 0.45);
          background: rgba(61, 92, 245, 0.12);
          color: #93acff;
          border-radius: 9999px;
          padding: 5px 16px;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          margin-bottom: 24px;
        }
        .landing-h1 {
          font-size: clamp(32px, 5vw, 56px);
          font-weight: 800;
          line-height: 1.1;
          letter-spacing: -0.03em;
          margin: 0 0 20px;
          color: #f0f4ff;
        }
        .landing-accent {
          background: linear-gradient(135deg, #5b7df8, #a78bfa);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }
        .landing-lead {
          font-size: 17px;
          line-height: 1.65;
          color: #8fa0bb;
          max-width: 600px;
          margin: 0 auto 36px;
        }
        .landing-cta {
          display: flex;
          gap: 12px;
          justify-content: center;
          flex-wrap: wrap;
        }
        .landing-btn-primary {
          background: #3d5cf5;
          border-color: #3d5cf5;
          color: #fff;
        }
        .landing-btn-primary:hover {
          background: #2d4de0;
          border-color: #2d4de0;
        }
        .landing-btn-outline {
          background: rgba(255,255,255,0.06);
          border-color: rgba(255,255,255,0.18);
          color: #e8edf5;
        }
        .landing-btn-outline:hover {
          background: rgba(255,255,255,0.12);
          border-color: rgba(255,255,255,0.28);
        }
        .landing-btn-lg {
          padding: 11px 24px;
          font-size: 15px;
          border-radius: 12px;
        }
        .landing-features {
          position: relative;
          z-index: 10;
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 16px;
          max-width: 1100px;
          margin: 0 auto 80px;
          padding: 0 24px;
        }
        .landing-feature-card {
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 16px;
          padding: 24px 20px;
          display: flex;
          flex-direction: column;
          gap: 10px;
          transition: background 0.2s, border-color 0.2s;
        }
        .landing-feature-card:hover {
          background: rgba(255,255,255,0.07);
          border-color: rgba(61, 92, 245, 0.3);
        }
        .landing-feature-icon { font-size: 28px; }
        .landing-feature-title { margin: 0; font-size: 16px; font-weight: 700; color: #e8edf5; }
        .landing-feature-desc  { margin: 0; font-size: 13px; color: #7d8fa8; line-height: 1.55; }
        .landing-footer {
          position: relative;
          z-index: 10;
          padding: 20px 48px;
          border-top: 1px solid rgba(255,255,255,0.06);
          font-size: 13px;
          color: #4a5d78;
          margin-top: auto;
        }
        @media (max-width: 900px) {
          .landing-features { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .landing-nav { padding: 16px 24px; }
        }
        @media (max-width: 520px) {
          .landing-features { grid-template-columns: 1fr; }
          .landing-hero { padding: 60px 16px 50px; }
        }
      `}</style>
    </div>
  );
}
