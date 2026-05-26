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
      error:   (message, duration) => addToast("error",   message, duration),
      warning: (message, duration) => addToast("warning", message, duration),
      info:    (message, duration) => addToast("info",    message, duration),
      dismiss: (id) => setToasts((prev) => prev.filter((t) => t.id !== id)),
      clear:   ()   => setToasts([]),
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
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

const TOAST_COLORS: Record<ToastType, { bg: string; border: string; color: string; icon: string }> = {
  success: { bg: "var(--success-bg)",  border: "var(--success-border)", color: "var(--success)", icon: "✓" },
  error:   { bg: "var(--danger-bg)",   border: "var(--danger-border)",  color: "var(--danger)",  icon: "✕" },
  warning: { bg: "var(--warning-bg)",  border: "var(--warning-border)", color: "var(--warning)", icon: "⚠" },
  info:    { bg: "var(--info-bg)",     border: "var(--info-border)",    color: "var(--info)",    icon: "ℹ" },
};

function ToastItem({ id, type, message, duration = 5000, onDismiss }: ToastProps) {
  useEffect(() => {
    if (duration <= 0) return;
    const timer = window.setTimeout(() => onDismiss(id), duration);
    return () => window.clearTimeout(timer);
  }, [id, duration, onDismiss]);

  const c = TOAST_COLORS[type];

  return (
    <div
      role="alert"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        justifyContent: "space-between",
        padding: "12px 14px",
        marginBottom: 8,
        borderRadius: "var(--radius)",
        border: `1px solid ${c.border}`,
        background: c.bg,
        color: c.color,
        minWidth: 280,
        maxWidth: 440,
        boxShadow: "var(--shadow-md)",
        animation: "slideIn 0.25s ease-out",
        fontFamily: "var(--font-body)",
        fontSize: 13,
        fontWeight: 600,
        lineHeight: 1.4,
      }}
    >
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 15, flexShrink: 0 }}>{c.icon}</span>
        <span>{message}</span>
      </span>
      <button
        type="button"
        onClick={() => onDismiss(id)}
        aria-label="Закрыть"
        style={{
          background: "transparent",
          border: "none",
          color: "inherit",
          cursor: "pointer",
          padding: "2px 4px",
          fontSize: 16,
          opacity: 0.65,
          lineHeight: 1,
          marginTop: 1,
          flexShrink: 0,
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
  const pos =
    position === "top-left"     ? { top: 72, left: 20 }
    : position === "bottom-right" ? { bottom: 20, right: 20 }
    : position === "bottom-left"  ? { bottom: 20, left: 20 }
    : { top: 72, right: 20 };

  return (
    <div style={{ position: "fixed", ...pos, zIndex: 9999, display: "flex", flexDirection: "column" }}>
      {toasts.map((t) => (
        <ToastItem key={t.id} {...t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

export default ToastContainer;
