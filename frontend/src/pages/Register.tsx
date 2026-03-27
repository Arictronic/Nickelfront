import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { isValidEmail, checkPasswordRequirements } from "../utils/validators";

interface PasswordRequirements {
  minLength: boolean;
  hasUpperCase: boolean;
  hasLowerCase: boolean;
  hasNumber: boolean;
  isValid: boolean;
}

function RequirementItem({ met, label }: { met: boolean; label: string }) {
  return (
    <div className={`password-requirement ${met ? "met" : ""}`}>
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        {met ? (
          <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" fill="currentColor" />
        ) : (
          <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="2" />
        )}
      </svg>
      <span>{label}</span>
    </div>
  );
}

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [agree, setAgree] = useState(false);
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");

  const passwordReqs: PasswordRequirements = checkPasswordRequirements(password);
  const passwordsMatch = confirmPassword && password === confirmPassword;
  const isEmailValid = isValidEmail(email);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!isEmailValid) {
      setError("Введите корректный email");
      return;
    }

    if (!passwordReqs.isValid) {
      setError("Пароль не соответствует требованиям");
      return;
    }

    if (!passwordsMatch) {
      setError("Пароли не совпадают");
      return;
    }

    if (!agree) {
      setError("Необходимо согласие с условиями");
      return;
    }

    try {
      await register({ email, password, username: username || undefined });
      navigate("/login");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка регистрации");
    }
  };

  return (
    <form className="auth panel" onSubmit={onSubmit}>
      <h2>Регистрация</h2>
      <p className="muted">Создайте аккаунт для доступа к платформе.</p>

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
        <input
          className="input"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Имя пользователя (необязательно)"
          type="text"
          autoComplete="username"
        />
      </div>

      <div className="form-group">
        <div className="password-input-wrapper">
          <input
            className={`input ${password && !passwordReqs.isValid ? "invalid" : ""}`}
            type={show ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
            autoComplete="new-password"
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

        <div className="password-requirements">
          <p className="requirements-title">Требования к паролю:</p>
          <RequirementItem met={passwordReqs.minLength} label="Минимум 8 символов" />
          <RequirementItem met={passwordReqs.hasUpperCase} label="Заглавная буква (A-Z)" />
          <RequirementItem met={passwordReqs.hasLowerCase} label="Строчная буква (a-z)" />
          <RequirementItem met={passwordReqs.hasNumber} label="Цифра (0-9)" />
        </div>
      </div>

      <div className="form-group">
        <div className="password-input-wrapper">
          <input
            className={`input ${confirmPassword && !passwordsMatch ? "invalid" : ""}`}
            type={show ? "text" : "password"}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Подтвердите пароль"
            autoComplete="new-password"
          />
          {confirmPassword && passwordsMatch && (
            <span className="password-match-success">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" fill="currentColor" />
              </svg>
              Пароли совпадают
            </span>
          )}
        </div>
        {confirmPassword && !passwordsMatch && (
          <span className="field-error">Пароли не совпадают</span>
        )}
      </div>

      <label className="checkbox-label">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span>
          Я согласен с <a href="/terms" target="_blank" rel="noopener noreferrer">условиями использования</a> и
          <a href="/privacy" target="_blank" rel="noopener noreferrer"> политикой конфиденциальности</a>
        </span>
      </label>

      <button className="btn btn-primary" type="submit" disabled={!passwordReqs.isValid || !passwordsMatch || !isEmailValid || !agree}>
        Зарегистрироваться
      </button>

      {error && <p className="error">{error}</p>}

      <Link className="muted" to="/login">
        Уже есть аккаунт? <strong>Войти</strong>
      </Link>
    </form>
  );
}
