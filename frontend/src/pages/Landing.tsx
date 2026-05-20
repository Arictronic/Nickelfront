import { useEffect, useRef } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

function ParticleCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    type Particle = { x: number; y: number; vx: number; vy: number; r: number; alpha: number };

    const COUNT = 80;
    const particles: Particle[] = Array.from({ length: COUNT }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: (Math.random() - 0.5) * 0.35,
      vy: (Math.random() - 0.5) * 0.35,
      r: Math.random() * 1.5 + 0.4,
      alpha: Math.random() * 0.4 + 0.15,
    }));

    const LINK_DIST = 120;

    const draw = () => {
      const W = canvas.width;
      const H = canvas.height;
      ctx.clearRect(0, 0, W, H);

      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x += W;
        if (p.x > W) p.x -= W;
        if (p.y < 0) p.y += H;
        if (p.y > H) p.y -= H;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${p.alpha})`;
        ctx.fill();
      }

      for (let i = 0; i < COUNT; i++) {
        for (let j = i + 1; j < COUNT; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < LINK_DIST) {
            const alpha = (1 - dist / LINK_DIST) * 0.08;
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.strokeStyle = `rgba(255, 255, 255, ${alpha})`;
            ctx.lineWidth = 0.7;
            ctx.stroke();
          }
        }
      }

      animId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}
    />
  );
}

const features = [
  { icon: "◈", title: "Парсинг статей", desc: "Автоматический сбор научных работ из открытых источников" },
  { icon: "⬡", title: "Семантический поиск", desc: "Поиск по смыслу с использованием векторных эмбеддингов" },
  { icon: "◉", title: "Аналитика", desc: "Графики, метрики и статистика по базе данных" },
];

export default function Landing() {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  if (isAuthenticated) return <Navigate to="/dashboard" replace />;

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#000",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px 24px",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <ParticleCanvas />

      <div
        style={{
          position: "relative",
          zIndex: 1,
          width: "100%",
          maxWidth: "680px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "44px",
          textAlign: "center",
        }}
      >
        {/* Badge */}
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            padding: "5px 14px",
            borderRadius: "999px",
            border: "1px solid rgba(255, 255, 255, 0.14)",
            fontSize: "11px",
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.5)",
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "#22c55e",
              boxShadow: "0 0 6px #22c55e",
              animation: "pulse-dot 2.2s ease-in-out infinite",
            }}
          />
          Research Platform
        </div>

        {/* Hero title */}
        <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          <h1
            style={{
              margin: 0,
              fontSize: "clamp(44px, 7vw, 80px)",
              fontWeight: 900,
              letterSpacing: "-0.05em",
              lineHeight: 1.0,
              color: "#ffffff",
            }}
          >
            Nickelfront
          </h1>
          <p
            style={{
              margin: 0,
              fontSize: "16px",
              color: "rgba(255,255,255,0.38)",
              lineHeight: 1.65,
              maxWidth: "480px",
              alignSelf: "center",
            }}
          >
            Платформа для работы с научными статьями: автоматический парсинг,
            семантический поиск и визуальная аналитика.
          </p>
        </div>

        {/* CTA buttons */}
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", justifyContent: "center" }}>
          <button
            className="btn btn-primary"
            onClick={() => navigate("/login")}
            style={{ minWidth: "140px", padding: "12px 28px", fontSize: "14px" }}
          >
            Войти
          </button>
          <button
            className="btn"
            onClick={() => navigate("/register")}
            style={{ minWidth: "140px", padding: "12px 28px", fontSize: "14px" }}
          >
            Регистрация
          </button>
        </div>

        {/* Feature cards */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: "12px",
            width: "100%",
          }}
        >
          {features.map((f) => (
            <div
              key={f.title}
              style={{
                padding: "20px 16px",
                borderRadius: "12px",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                background: "rgba(255, 255, 255, 0.03)",
                backdropFilter: "blur(12px)",
                WebkitBackdropFilter: "blur(12px)",
                textAlign: "left",
                transition: "border-color 0.18s, transform 0.18s",
                cursor: "default",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLDivElement).style.borderColor = "rgba(255, 255, 255, 0.18)";
                (e.currentTarget as HTMLDivElement).style.transform = "translateY(-2px)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLDivElement).style.borderColor = "rgba(255, 255, 255, 0.08)";
                (e.currentTarget as HTMLDivElement).style.transform = "";
              }}
            >
              <div style={{ fontSize: "18px", marginBottom: "10px", color: "rgba(255,255,255,0.5)", lineHeight: 1 }}>
                {f.icon}
              </div>
              <div style={{ fontSize: "13px", fontWeight: 700, color: "#ffffff", marginBottom: "5px" }}>
                {f.title}
              </div>
              <div style={{ fontSize: "12px", color: "rgba(255,255,255,0.3)", lineHeight: 1.5 }}>
                {f.desc}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}