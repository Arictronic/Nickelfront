import type { PropsWithChildren } from "react";

interface ModalProps extends PropsWithChildren {
  title?: string;
  onClose?: () => void;
  maxWidth?: number;
}

export default function Modal({ title, onClose, maxWidth = 560, children }: ModalProps) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(7, 13, 26, 0.65)",
        backdropFilter: "blur(4px)",
        zIndex: 200,
        display: "grid",
        placeItems: "center",
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        className="panel"
        style={{ width: "100%", maxWidth, maxHeight: "90vh", overflowY: "auto" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {(title || onClose) && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 16,
              gap: 12,
            }}
          >
            {title && (
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--text)" }}>
                {title}
              </h3>
            )}
            {onClose && (
              <button
                className="icon-btn"
                onClick={onClose}
                aria-label="Закрыть"
                style={{ marginLeft: "auto", flexShrink: 0 }}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
