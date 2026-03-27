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
  const isPasswordFilled = password.length >= 6;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!isEmailValid) {
      setError("Введите корректный email");
      return;
    }

    if (!isPasswordFilled) {
      setError("Введите пароль (минимум 6 символов)");
      return;
    }

    try {
      await login({ email, password });
      setTimeout(() => {
        navigate("/dashboard", { replace: true });
      }, 100);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка входа");
    }
  };

  return (
    <form className="auth panel" onSubmit={onSubmit}>
      <h2>Вход</h2>
      <p className="muted">Войдите, чтобы продолжить работу.</p>

      <div className="form-group">
        <input
          className={`input ${email && !isEmailValid ? "invalid" : ""}`}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          type="email"
          autoComplete="email"
        />
        {email && !isEmailValid && (
          <span className="field-error">Введите корректный email</span>
        )}
      </div>

      <div className="form-group">
        <div className="password-input-wrapper">
          <input
            className="input"
            type={show ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
            autoComplete="current-password"
          />
          <button
            className="icon-btn toggle-password"
            type="button"
            onClick={() => setShow((s) => !s)}
            aria-label="Показать пароль"
            tabIndex={-1}
          >
            {show ? (
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path d="M3 4l17 17" stroke="currentColor" strokeWidth="2" fill="none" />
                <path
                  d="M10.6 10.7a2.5 2.5 0 003.1 3.1M9.9 5.1A9.8 9.8 0 0112 5c5.6 0 9 7 9 7a16.1 16.1 0 01-3.3 4.1M6.5 7.6C3.8 9.4 2 12 2 12s3.4 7 10 7c1.8 0 3.4-.4 4.8-1.1"
                  stroke="currentColor"
                  strokeWidth="2"
                  fill="none"
                />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path
                  d="M2 12s3.4-7 10-7 10 7 10 7-3.4 7-10 7-10-7-10-7z"
                  stroke="currentColor"
                  strokeWidth="2"
                  fill="none"
                />
                <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" fill="none" />
              </svg>
            )}
          </button>
        </div>
        {password && password.length < 6 && (
          <span className="field-error">Минимум 6 символов</span>
        )}
      </div>

      <label className="checkbox-label">
        <input type="checkbox" /> Запомнить меня
      </label>

      <button className="btn btn-primary" type="submit" disabled={!isEmailValid || !isPasswordFilled}>
        Войти
      </button>

      {error && <p className="error">{error}</p>}

      <Link className="muted" to="/register">
        Нет аккаунта? <strong>Зарегистрироваться</strong>
      </Link>
    </form>
  );
}
