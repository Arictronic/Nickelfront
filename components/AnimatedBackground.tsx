import { useEffect, useRef } from "react";
import { useTheme } from "../context/ThemeProvider";

type Particle = { x: number; y: number; vx: number; vy: number; life: number; maxLife: number; size: number };

export default function AnimatedBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let W = window.innerWidth;
    let H = window.innerHeight;
    canvas.width = W;
    canvas.height = H;

    const isDark = theme === "dark";

    // color helpers
    const c = (r: number, g: number, b: number, a: number) =>
      isDark ? `rgba(${r},${g},${b},${a})` : `rgba(${255 - r},${255 - g},${255 - b},${a * 0.6})`;

    // ── Glowing orbs ──────────────────────────────────────────
    type Orb = { x: number; y: number; r: number; vx: number; vy: number; phase: number };
    const orbs: Orb[] = [
      { x: W * 0.18, y: H * 0.22, r: Math.hypot(W, H) * 0.52, vx: 0.035, vy: 0.025, phase: 0 },
      { x: W * 0.82, y: H * 0.78, r: Math.hypot(W, H) * 0.46, vx: -0.028, vy: -0.038, phase: Math.PI },
      { x: W * 0.55, y: H * 0.12, r: Math.hypot(W, H) * 0.38, vx: -0.042, vy: 0.032, phase: 2.2 },
    ];
    const accents: Orb[] = [
      { x: W * 0.3,  y: H * 0.6,  r: Math.hypot(W, H) * 0.22, vx: 0.18, vy: -0.14, phase: 0.8 },
      { x: W * 0.7,  y: H * 0.35, r: Math.hypot(W, H) * 0.18, vx: -0.22, vy: 0.16, phase: 2.5 },
      { x: W * 0.15, y: H * 0.8,  r: Math.hypot(W, H) * 0.16, vx: 0.19, vy: 0.12, phase: 1.1 },
      { x: W * 0.85, y: H * 0.2,  r: Math.hypot(W, H) * 0.14, vx: -0.15, vy: -0.18, phase: 3.7 },
    ];

    // ── Floating particles ────────────────────────────────────
    const MAX_PARTICLES = 60;
    const particles: Particle[] = [];
    function spawnParticle() {
      particles.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.35,
        vy: -0.2 - Math.random() * 0.4,
        life: 0,
        maxLife: 180 + Math.random() * 240,
        size: 1 + Math.random() * 1.8,
      });
    }
    for (let i = 0; i < MAX_PARTICLES; i++) {
      spawnParticle();
      particles[i].life = Math.random() * particles[i].maxLife;
    }

    function drawOrb(orb: Orb, ca: number, ma: number) {
      const g = ctx!.createRadialGradient(orb.x, orb.y, 0, orb.x, orb.y, orb.r);
      g.addColorStop(0,    c(255, 255, 255, ca));
      g.addColorStop(0.28, c(255, 255, 255, ma));
      g.addColorStop(0.7,  c(255, 255, 255, ma * 0.18));
      g.addColorStop(1,    c(255, 255, 255, 0));
      ctx!.beginPath();
      ctx!.arc(orb.x, orb.y, orb.r, 0, Math.PI * 2);
      ctx!.fillStyle = g;
      ctx!.fill();
    }

    function moveOrb(orb: Orb, t: number, speed: number) {
      orb.x += orb.vx + Math.sin(t * speed + orb.phase) * 0.28;
      orb.y += orb.vy + Math.cos(t * speed * 0.75 + orb.phase) * 0.22;
      if (orb.x < -orb.r) orb.x = W + orb.r;
      if (orb.x > W + orb.r) orb.x = -orb.r;
      if (orb.y < -orb.r) orb.y = H + orb.r;
      if (orb.y > H + orb.r) orb.y = -orb.r;
    }

    function drawGrid(t: number) {
      const STEP = 70;
      const alpha = isDark ? 0.055 : 0.04;
      const breathe = 0.7 + 0.3 * Math.sin(t * 0.00045);
      ctx!.strokeStyle = isDark
        ? `rgba(255,255,255,${alpha * breathe})`
        : `rgba(0,0,0,${alpha * breathe})`;
      ctx!.lineWidth = 0.5;
      ctx!.beginPath();
      for (let x = 0; x < W; x += STEP) {
        ctx!.moveTo(x, 0);
        ctx!.lineTo(x, H);
      }
      for (let y = 0; y < H; y += STEP) {
        ctx!.moveTo(0, y);
        ctx!.lineTo(W, y);
      }
      ctx!.stroke();

      // grid intersection dots
      const dotAlpha = isDark ? 0.12 * breathe : 0.08 * breathe;
      ctx!.fillStyle = isDark ? `rgba(255,255,255,${dotAlpha})` : `rgba(0,0,0,${dotAlpha})`;
      for (let x = 0; x < W; x += STEP) {
        for (let y = 0; y < H; y += STEP) {
          ctx!.beginPath();
          ctx!.arc(x, y, 1.2, 0, Math.PI * 2);
          ctx!.fill();
        }
      }
    }

    function drawScanLine(t: number) {
      const y = ((t * 0.022) % (H + 80)) - 40;
      const g = ctx!.createLinearGradient(0, y - 20, 0, y + 20);
      const a = isDark ? 0.07 : 0.04;
      g.addColorStop(0, `rgba(255,255,255,0)`);
      g.addColorStop(0.5, isDark ? `rgba(255,255,255,${a})` : `rgba(0,0,0,${a})`);
      g.addColorStop(1, `rgba(255,255,255,0)`);
      ctx!.fillStyle = g;
      ctx!.fillRect(0, y - 20, W, 40);
    }

    function drawParticles() {
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.life++;
        if (p.life > p.maxLife) {
          particles.splice(i, 1);
          spawnParticle();
          continue;
        }
        const progress = p.life / p.maxLife;
        const alpha = isDark
          ? Math.sin(progress * Math.PI) * 0.55
          : Math.sin(progress * Math.PI) * 0.3;
        ctx!.beginPath();
        ctx!.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx!.fillStyle = isDark ? `rgba(255,255,255,${alpha})` : `rgba(0,0,0,${alpha})`;
        ctx!.fill();
      }
    }

    function drawSpotlights(t: number) {
      const spots = [
        { bx: W * 0.25, by: H * 0.3, freq: 0.00022, amp: W * 0.12 },
        { bx: W * 0.72, by: H * 0.65, freq: 0.00018, amp: W * 0.1 },
      ];
      for (const s of spots) {
        const x = s.bx + Math.sin(t * s.freq + 1.2) * s.amp;
        const y = s.by + Math.cos(t * s.freq * 0.9) * s.amp * 0.7;
        const r = Math.hypot(W, H) * 0.09;
        const g = ctx!.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0,   isDark ? "rgba(255,255,255,0.32)" : "rgba(0,0,0,0.14)");
        g.addColorStop(0.4, isDark ? "rgba(255,255,255,0.1)"  : "rgba(0,0,0,0.05)");
        g.addColorStop(1,   "rgba(255,255,255,0)");
        ctx!.beginPath();
        ctx!.arc(x, y, r, 0, Math.PI * 2);
        ctx!.fillStyle = g;
        ctx!.fill();
      }
    }

    const tick = (t: number) => {
      ctx.clearRect(0, 0, W, H);

      // deep orbs
      for (const orb of orbs) {
        moveOrb(orb, t, 0.00011);
        drawOrb(orb, isDark ? 0.28 : 0.18, isDark ? 0.10 : 0.06);
      }

      // accent orbs
      for (const orb of accents) {
        moveOrb(orb, t, 0.00028);
        drawOrb(orb, isDark ? 0.42 : 0.22, isDark ? 0.15 : 0.08);
      }

      drawSpotlights(t);
      drawGrid(t);
      drawScanLine(t);
      drawParticles();

      animId = requestAnimationFrame(tick);
    };

    animId = requestAnimationFrame(tick);

    const onResize = () => {
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.width = W;
      canvas.height = H;
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", onResize);
    };
  }, [theme]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "fixed",
        inset: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        zIndex: 0,
      }}
    />
  );
}