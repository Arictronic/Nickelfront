import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import * as authApi from "./api/auth";
import Layout from "./components/layout/Layout";
import Dashboard from "./pages/Dashboard";
import Patents from "./pages/Patents";
import PatentDetail from "./pages/PatentDetail";
import Analytics from "./pages/Analytics";
import AlloyAnalysis from "./pages/AlloyAnalysis";
import Metrics from "./pages/Metrics";
import CeleryMonitoring from "./pages/CeleryMonitoring";
import WorkerStatus from "./pages/WorkerStatus";
import Database from "./pages/Database";
import TechnicalSettings from "./pages/TechnicalSettings";
import PaperReport from "./pages/PaperReport";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Landing from "./pages/Landing";
import { useAuthStore } from "./store/authStore";
import ErrorBoundary from "./components/ErrorBoundary";
import { ToastProvider } from "./components/ui/Toast";


function StaticInfoPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="page" style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      <div className="panel">
        <h2>{title}</h2>
        <div style={{ lineHeight: 1.65 }}>{children}</div>
      </div>
    </div>
  );
}

function SessionCheckingNotice() {
  return (
    <div className="page" style={{ padding: 24 }}>
      <div className="panel">Проверка сессии...</div>
    </div>
  );
}

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isSessionChecking = useAuthStore((s) => s.isSessionChecking);

  if (isSessionChecking) return <SessionCheckingNotice />;
  return isAuthenticated ? children : <Navigate to="/login" replace />;
}

function AdminRoute({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isSessionChecking = useAuthStore((s) => s.isSessionChecking);
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user && user.is_admin;

  if (isSessionChecking) return <SessionCheckingNotice />;

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return isAdmin ? children : <Navigate to="/dashboard" replace />;
}

function RootRedirect() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return <Navigate to={isAuthenticated ? "/dashboard" : "/"} replace />;
}

function AuthOnlyRoute({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isSessionChecking = useAuthStore((s) => s.isSessionChecking);

  if (isSessionChecking) return <SessionCheckingNotice />;
  return isAuthenticated ? <Navigate to="/dashboard" replace /> : children;
}

function PageBoundary({ name, children }: { name: string; children: ReactNode }) {
  return <ErrorBoundary name={name}>{children}</ErrorBoundary>;
}

function ProtectedPage({ name, children }: { name: string; children: JSX.Element }) {
  return (
    <ProtectedRoute>
      <PageBoundary name={name}>{children}</PageBoundary>
    </ProtectedRoute>
  );
}

function AdminPage({ name, children }: { name: string; children: JSX.Element }) {
  return (
    <AdminRoute>
      <PageBoundary name={name}>{children}</PageBoundary>
    </AdminRoute>
  );
}

function SessionBootstrap() {
  const token = useAuthStore((s) => s.token);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const setUser = useAuthStore((s) => s.setUser);
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const setSessionChecking = useAuthStore((s) => s.setSessionChecking);
  const setSessionError = useAuthStore((s) => s.setSessionError);

  useEffect(() => {
    if (!token && !refreshToken) {
      setSessionChecking(false);
      setAuthenticated(false);
      setUser(null);
      setSessionError(null);
      return;
    }

    let active = true;
    setSessionChecking(true);
    setSessionError(null);

    authApi
      .getCurrentUser()
      .then((user) => {
        if (!active) return;
        setUser(user);
        setAuthenticated(true);
        setSessionError(null);
      })
      .catch((error) => {
        if (!active) return;
        const status = error?.response?.status;

        // Backend cleanup removes refresh_tokens. Old browser tokens then become stale.
        // Clear auth only for explicit auth errors. Network/proxy/backend errors should not
        // erase the user session just because the backend is still starting.
        if (status === 401 || status === 403) {
          localStorage.removeItem("auth_token");
          localStorage.removeItem("refresh_token");
          setUser(null);
          setAuthenticated(false);
          setSessionError(null);
          return;
        }

        console.warn("Session check failed without auth status", error);
        setUser(null);
        setAuthenticated(!!token || !!refreshToken);
        setSessionError("backend_unavailable");
      })
      .finally(() => {
        if (!active) return;
        setSessionChecking(false);
      });

    return () => {
      active = false;
    };
  }, [token, refreshToken, setUser, setAuthenticated, setSessionChecking, setSessionError]);

  return null;
}

export default function App() {
  return (
    <ToastProvider>
      <SessionBootstrap />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="/login"
          element={
            <AuthOnlyRoute>
              <PageBoundary name="Вход">
                <Login />
              </PageBoundary>
            </AuthOnlyRoute>
          }
        />

        <Route
          path="/terms"
          element={
            <PageBoundary name="Условия использования">
              <StaticInfoPage title="Условия использования">
                <p>Nickelfront используется как исследовательская и учебная система для работы со статьями, патентами и отчётами.</p>
                <p>Не загружайте секретные ключи, закрытые документы и персональные данные без необходимости. Администратор проекта отвечает за доступ пользователей и сохранность данных.</p>
              </StaticInfoPage>
            </PageBoundary>
          }
        />
        <Route
          path="/privacy"
          element={
            <PageBoundary name="Политика конфиденциальности">
              <StaticInfoPage title="Политика конфиденциальности">
                <p>Данные проекта хранятся в локальной базе Nickelfront и используются для поиска, анализа, RAG, отчётов и фоновой обработки.</p>
                <p>Не публикуйте токены, пароли, API-ключи и приватные документы. При попадании секретов в архив, git или чат их нужно заменить.</p>
              </StaticInfoPage>
            </PageBoundary>
          }
        />
        <Route
          path="/register"
          element={
            <AuthOnlyRoute>
              <PageBoundary name="Регистрация">
                <Register />
              </PageBoundary>
            </AuthOnlyRoute>
          }
        />
        <Route element={<Layout />}>
          <Route path="/dashboard" element={<ProtectedPage name="Главная"><Dashboard /></ProtectedPage>} />
          <Route path="/papers" element={<ProtectedPage name="Статьи"><Patents /></ProtectedPage>} />
          <Route path="/papers/:id" element={<ProtectedPage name="Карточка статьи"><PatentDetail /></ProtectedPage>} />
          <Route path="/papers/:id/report" element={<ProtectedPage name="Отчёт по статье"><PaperReport /></ProtectedPage>} />
          <Route path="/vector-search" element={<ProtectedPage name="Векторный поиск"><Navigate to="/search" replace /></ProtectedPage>} />
          <Route path="/metrics" element={<ProtectedPage name="Метрики и Аналитика"><Metrics /></ProtectedPage>} />
          <Route path="/celery" element={<AdminPage name="Мониторинг Celery"><CeleryMonitoring /></AdminPage>} />
          <Route path="/search" element={<ProtectedPage name="Поиск"><Analytics /></ProtectedPage>} />
          <Route path="/analysis" element={<ProtectedPage name="Анализ сплавов"><AlloyAnalysis /></ProtectedPage>} />
          <Route path="/jobs" element={<ProtectedPage name="Статус парсинга"><WorkerStatus /></ProtectedPage>} />
          <Route path="/database" element={<AdminPage name="База данных"><Database /></AdminPage>} />
          <Route path="/settings" element={<AdminPage name="Технические настройки"><TechnicalSettings /></AdminPage>} />
        </Route>
        <Route path="*" element={<RootRedirect />} />
      </Routes>
    </ToastProvider>
  );
}
