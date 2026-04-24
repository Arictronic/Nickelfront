import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

export default function Landing() {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  return (
    <div className="lux-landing page">
      <div className="lux-background" aria-hidden="true">
        <div className="lux-noise" />
        <div className="lux-vignette" />
        <div className="lux-wave wave-gold" />
        <div className="lux-wave wave-ivory" />
        <div className="lux-wave wave-shadow" />
        <div className="lux-caustic caustic-one" />
        <div className="lux-caustic caustic-two" />
        <div className="lux-dust dust-one" />
        <div className="lux-dust dust-two" />
        <div className="lux-dust dust-three" />
      </div>

      <section className="lux-hero">
        <div className="lux-frame lux-frame-top" />
        <div className="lux-frame lux-frame-right" />

        <div className="lux-kicker-wrap">
          <span className="lux-kicker">Nickelfront</span>
          <span className="lux-kicker-line" />
        </div>

        <div className="lux-copy">
          <p className="lux-index">01 / Swiss minimal landing</p>
          <h1>
            Intelligence for
            <br />
            materials research.
          </h1>
          <p className="lux-description">
            A refined interface for navigating scientific knowledge — reduced to light, motion,
            silence and precision. Dark polished surfaces, fluid luminous layers and a calm,
            gallery-like composition built for focus.
          </p>
        </div>

        <div className="lux-meta-grid">
          <div className="lux-meta-card">
            <span>Mode</span>
            <strong>Obsidian / Gold</strong>
          </div>
          <div className="lux-meta-card">
            <span>Visual language</span>
            <strong>Swiss minimalism</strong>
          </div>
          <div className="lux-meta-card">
            <span>Atmosphere</span>
            <strong>Silk wave motion</strong>
          </div>
        </div>

        <div className="lux-cta-row">
          <button
            type="button"
            className="lux-cta"
            onClick={() => navigate(isAuthenticated ? "/dashboard" : "/login")}
          >
            <span className="lux-cta-glow" aria-hidden="true" />
            <span className="lux-cta-label">Enter experience</span>
          </button>
        </div>
      </section>
    </div>
  );
}
