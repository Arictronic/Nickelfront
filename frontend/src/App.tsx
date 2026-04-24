import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import * as authApi from "./api/auth";
import Layout from "./components/layout/Layout";
import Dashboard from "./pages/Dashboard";
import Patents from "./pages/Patents";
import PatentDetail from "./pages/PatentDetail";
import Analytics from "./pages/Analytics";
import Metrics from "./pages/Metrics";
import CeleryMonitoring from "./pages/CeleryMonitoring";
import WorkerStatus from "./pages/WorkerStatus";
import Database from "./pages/Database";
import PaperReport from "./pages/PaperReport";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Landing from "./pages/Landing";
import { useAuthStore } from "./store/authStore";
import ErrorBoundary from "./components/ErrorBoundary";

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return isAuthenticated ? children : <Navigate to="/login" replace />;
}

function AdminRoute({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user && user.is_admin;

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
  return isAuthenticated ? <Navigate to="/dashboard" replace /> : children;
}

function SessionBootstrap() {
  const token = useAuthStore((s) => s.token);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const setUser = useAuthStore((s) => s.setUser);
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const setSessionChecking = useAuthStore((s) => s.setSessionChecking);

  useEffect(() => {
    if (!token && !refreshToken) {
      setSessionChecking(false);
      setAuthenticated(false);
      setUser(null);
      return;
    }

    let active = true;
    setSessionChecking(true);

    authApi
      .getCurrentUser()
      .then((user) => {
        if (!active) return;
        setUser(user);
        setAuthenticated(true);
      })
      .catch(() => {
        if (!active) return;
        setUser(null);
        setAuthenticated(!!token || !!refreshToken);
      })
      .finally(() => {
        if (!active) return;
        setSessionChecking(false);
      });

    return () => {
      active = false;
    };
  }, [token, refreshToken, setUser, setAuthenticated, setSessionChecking]);

  return null;
}

export default function App() {
  return (
    <>
      <SessionBootstrap />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="/login"
          element={
            <AuthOnlyRoute>
              <Login />
            </AuthOnlyRoute>
          }
        />
        <Route
          path="/register"
          element={
            <AuthOnlyRoute>
              <Register />
            </AuthOnlyRoute>
          }
        />
        <Route element={<Layout />}>
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/papers"
            element={
              <ProtectedRoute>
                <Patents />
              </ProtectedRoute>
            }
          />
          <Route
            path="/papers/:id"
            element={
              <ProtectedRoute>
                <PatentDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/papers/:id/report"
            element={
              <ProtectedRoute>
                <PaperReport />
              </ProtectedRoute>
            }
          />
          <Route
            path="/vector-search"
            element={
              <ProtectedRoute>
                <Navigate to="/search" replace />
              </ProtectedRoute>
            }
          />
          <Route
            path="/metrics"
            element={
              <ProtectedRoute>
                <Metrics />
              </ProtectedRoute>
            }
          />
          <Route
            path="/celery"
            element={
              <AdminRoute>
                <CeleryMonitoring />
              </AdminRoute>
            }
          />
          <Route
            path="/search"
            element={
              <ProtectedRoute>
                <Analytics />
              </ProtectedRoute>
            }
          />
          <Route
            path="/jobs"
            element={
              <ProtectedRoute>
                <WorkerStatus />
              </ProtectedRoute>
            }
          />
          <Route
            path="/database"
            element={
              <AdminRoute>
                <ErrorBoundary name="База данных">
                  <Database />
                </ErrorBoundary>
              </AdminRoute>
            }
          />
        </Route>
        <Route path="*" element={<RootRedirect />} />
      </Routes>
    </>
  );
}
