import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ToastType = "success" | "error" | "info" | "warning";

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

interface ToastProps extends Toast {
  onDismiss: (id: string) => void;
}

type ToastApi = {
  toasts: Toast[];
  success: (message: string, duration?: number) => string;
  error: (message: string, duration?: number) => string;
  warning: (message: string, duration?: number) => string;
  info: (message: string, duration?: number) => string;
  dismiss: (id: string) => void;
  clear: () => void;
};

const ToastContext = createContext<ToastApi | null>(null);

function useToastState(): ToastApi {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const api = useMemo<ToastApi>(() => {
    const addToast = (type: ToastType, message: string, duration?: number) => {
      const id = `${Date.now()}-${Math.random()}`;
      setToasts((prev) => [...prev, { id, type, message, duration }]);
      return id;
    };

    return {
      toasts,
      success: (message, duration) => addToast("success", message, duration),
      error: (message, duration) => addToast("error", message, duration),
      warning: (message, duration) => addToast("warning", message, duration),
      info: (message, duration) => addToast("info", message, duration),
      dismiss: (id) => setToasts((prev) => prev.filter((toast) => toast.id !== id)),
      clear: () => setToasts([]),
    };
  }, [toasts]);

  return api;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const api = useToastState();
  return <ToastContext.Provider value={api}>{children}</ToastContext.Provider>;
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside ToastProvider");
  }
  return ctx;
}

/** Компонент отдельного Toast уведомления. */
function ToastItem({ id, type, message, duration = 5000, onDismiss }: ToastProps) {
  useEffect(() => {
    if (duration <= 0) return;
    const timer = window.setTimeout(() => onDismiss(id), duration);
    return () => window.clearTimeout(timer);
  }, [id, duration, onDismiss]);

  const getStyles = () => {
    const base = {
      padding: "12px 16px",
      borderRadius: 8,
      marginBottom: 8,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 12,
      boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
      minWidth: 300,
      maxWidth: 500,
      animation: "slideIn 0.3s ease-out",
    } as const;

    switch (type) {
      case "success":
        return { ...base, background: "#22c55e", color: "white" };
      case "error":
        return { ...base, background: "#ef4444", color: "white" };
      case "warning":
        return { ...base, background: "#f59e0b", color: "white" };
      case "info":
      default:
        return { ...base, background: "#4a6cf7", color: "white" };
    }
  };

  const icon = type === "success" ? "✓" : type === "error" ? "✕" : type === "warning" ? "⚠" : "ℹ";

  return (
    <div style={getStyles()} role="alert">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 18 }}>{icon}</span>
        <span>{message}</span>
      </div>
      <button
        type="button"
        onClick={() => onDismiss(id)}
        aria-label="Закрыть уведомление"
        style={{
          background: "transparent",
          border: "none",
          color: "inherit",
          cursor: "pointer",
          padding: 4,
          fontSize: 18,
          opacity: 0.8,
        }}
      >
        ×
      </button>
    </div>
  );
}

interface ToastContainerProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
  position?: "top-right" | "top-left" | "bottom-right" | "bottom-left";
}

export function ToastContainer({ toasts, onDismiss, position = "top-right" }: ToastContainerProps) {
  const positionStyles =
    position === "top-left"
      ? { top: 20, left: 20 }
      : position === "bottom-right"
        ? { bottom: 20, right: 20 }
        : position === "bottom-left"
          ? { bottom: 20, left: 20 }
          : { top: 20, right: 20 };

  return (
    <div
      style={{
        position: "fixed",
        ...positionStyles,
        zIndex: 9999,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} {...toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

export default ToastContainer;
