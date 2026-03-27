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
import FullTextSearch from "./pages/FullTextSearch";
import WorkerStatus from "./pages/WorkerStatus";
import Database from "./pages/Database";
import Landing from "./pages/Landing";
import PaperReport from "./pages/PaperReport";
import Login from "./pages/Login";
import Register from "./pages/Register";
import { useAuthStore } from "./store/authStore";

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return isAuthenticated ? children : <Navigate to="/login" replace />;
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
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/" element={<Layout />}>
          <Route index element={<Landing />} />
          <Route
            path="dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="papers"
            element={
              <ProtectedRoute>
                <Patents />
              </ProtectedRoute>
            }
          />
          <Route
            path="papers/:id"
            element={
              <ProtectedRoute>
                <PatentDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="papers/:id/report"
            element={
              <ProtectedRoute>
                <PaperReport />
              </ProtectedRoute>
            }
          />
          <Route
            path="vector-search"
            element={
              <ProtectedRoute>
                <Analytics />
              </ProtectedRoute>
            }
          />
          <Route
            path="metrics"
            element={
              <ProtectedRoute>
                <Metrics />
              </ProtectedRoute>
            }
          />
          <Route
            path="celery"
            element={
              <ProtectedRoute>
                <CeleryMonitoring />
              </ProtectedRoute>
            }
          />
          <Route
            path="search"
            element={
              <ProtectedRoute>
                <FullTextSearch />
              </ProtectedRoute>
            }
          />
          <Route
            path="jobs"
            element={
              <ProtectedRoute>
                <WorkerStatus />
              </ProtectedRoute>
            }
          />
          <Route
            path="database"
            element={
              <ProtectedRoute>
                <Database />
              </ProtectedRoute>
            }
          />
        </Route>
      </Routes>
    </>
  );
}
