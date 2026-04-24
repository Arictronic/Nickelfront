import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/layout/Layout";
import Dashboard from "./pages/Dashboard";
import Patents from "./pages/Patents";
import PatentDetail from "./pages/PatentDetail";
import Analytics from "./pages/Analytics";
import WorkerStatus from "./pages/WorkerStatus";
import Database from "./pages/Database";
import PaperReport from "./pages/PaperReport";
import Login from "./pages/Login";
import Register from "./pages/Register";
import { useAuthStore } from "./store/authStore";

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return isAuthenticated ? children : <Navigate to="/login" replace />;
}

function RootRedirect() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return <Navigate to={isAuthenticated ? "/dashboard" : "/login"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<Layout />}>
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
  );
}
