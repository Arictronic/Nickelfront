import { useState, useEffect } from "react";

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

/**
 * Компонент отдельного Toast уведомления.
 */
function ToastItem({ id, type, message, duration = 5000, onDismiss }: ToastProps) {
  useEffect(() => {
    if (duration > 0) {
      const timer = setTimeout(() => {
        onDismiss(id);
      }, duration);
      return () => clearTimeout(timer);
    }
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
    };

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

  const getIcon = () => {
    switch (type) {
      case "success":
        return "✓";
      case "error":
        return "✕";
      case "warning":
        return "⚠";
      case "info":
      default:
        return "ℹ";
    }
  };

  return (
    <div style={getStyles()} role="alert">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 18 }}>{getIcon()}</span>
        <span>{message}</span>
      </div>
      <button
        onClick={() => onDismiss(id)}
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

/**
 * Контейнер для Toast уведомлений.
 */
interface ToastContainerProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
  position?: "top-right" | "top-left" | "bottom-right" | "bottom-left";
}

export function ToastContainer({ toasts, onDismiss, position = "top-right" }: ToastContainerProps) {
  const getPositionStyles = () => {
    switch (position) {
      case "top-right":
        return { top: 20, right: 20 };
      case "top-left":
        return { top: 20, left: 20 };
      case "bottom-right":
        return { bottom: 20, right: 20 };
      case "bottom-left":
        return { bottom: 20, left: 20 };
      default:
        return { top: 20, right: 20 };
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        ...getPositionStyles(),
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

/**
 * Хук для управления Toast уведомлениями.
 */
export function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = (type: ToastType, message: string, duration?: number) => {
    const id = `${Date.now()}-${Math.random()}`;
    const toast: Toast = { id, type, message, duration };
    setToasts((prev) => [...prev, toast]);
    return id;
  };

  const dismissToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const success = (message: string, duration?: number) => addToast("success", message, duration);
  const error = (message: string, duration?: number) => addToast("error", message, duration);
  const warning = (message: string, duration?: number) => addToast("warning", message, duration);
  const info = (message: string, duration?: number) => addToast("info", message, duration);

  return {
    toasts,
    success,
    error,
    warning,
    info,
    dismiss: dismissToast,
    clear: () => setToasts([]),
  };
}

export default ToastContainer;
