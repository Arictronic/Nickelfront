import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { isValidEmail } from "../utils/validators";

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");

  const isEmailValid = isValidEmail(email);
  const isPasswordFilled = password.length >= 5;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!isEmailValid) {
      setError("Введите корректный email");
      return;
    }

    if (!isPasswordFilled) {
      setError("Введите пароль (минимум 5 символов)");
      return;
    }

    try {
      await login({ email, password });
      setTimeout(() => navigate("/dashboard", { replace: true }), 100);
    } catch (err: any) {
      if (err?.response?.status === 401) {
        setError("Неверный email или пароль");
        return;
      }
      setError(err.response?.data?.detail || "Ошибка входа");
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        display: "grid",
        placeItems: "center",
        padding: 24,
      }}
    >
      <form className="auth panel" onSubmit={onSubmit}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
          <div className="brand-mark">N</div>
          <span style={{ fontWeight: 800, fontSize: 18, letterSpacing: "-0.3px" }}>Nickelfront</span>
        </div>

        <h2 style={{ marginBottom: 4 }}>Вход в систему</h2>
        <p className="muted" style={{ marginBottom: 24 }}>Войдите, чтобы продолжить работу.</p>

        <div className="form-group">
          <label className="form-label" htmlFor="email">Email</label>
          <input
            id="email"
            className={`input${email && !isEmailValid ? " invalid" : ""}`}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            type="email"
            autoComplete="email"
          />
          {email && !isEmailValid && (
            <span className="field-error">Введите корректный email</span>
          )}
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="password">Пароль</label>
          <div className="password-input-wrapper">
            <input
              id="password"
              className="input"
              type={show ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Ваш пароль"
              autoComplete="current-password"
            />
            <button
              className="toggle-password"
              type="button"
              onClick={() => setShow((s) => !s)}
              aria-label="Показать/скрыть пароль"
              tabIndex={-1}
            >
              {show ? (
                <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 4l17 17M10.6 10.7a2.5 2.5 0 003.1 3.1M9.9 5.1A9.8 9.8 0 0112 5c5.6 0 9 7 9 7a16.1 16.1 0 01-3.3 4.1M6.5 7.6C3.8 9.4 2 12 2 12s3.4 7 10 7c1.8 0 3.4-.4 4.8-1.1" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M2 12s3.4-7 10-7 10 7 10 7-3.4 7-10 7-10-7-10-7z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              )}
            </button>
          </div>
          {password && password.length < 5 && (
            <span className="field-error">Минимум 5 символов</span>
          )}
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: 14 }}>
            {error}
          </div>
        )}

        <button
          className="btn btn-primary"
          type="submit"
          disabled={!isEmailValid || !isPasswordFilled}
          style={{ width: "100%", padding: "10px", fontSize: 14, marginBottom: 16 }}
        >
          Войти
        </button>

        <p style={{ margin: 0, fontSize: 13, color: "var(--muted)", textAlign: "center" }}>
          Нет аккаунта?{" "}
          <Link to="/register" style={{ color: "var(--primary)", fontWeight: 600, textDecoration: "none" }}>
            Зарегистрироваться
          </Link>
        </p>
      </form>
    </div>
  );
}
