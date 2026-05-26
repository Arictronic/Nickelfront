import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "default" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}

export default function Button({
  variant = "default",
  size,
  loading,
  icon,
  className = "",
  children,
  disabled,
  ...props
}: ButtonProps) {
  const variantClass =
    variant === "primary" ? "btn-primary"
    : variant === "ghost"   ? "btn-ghost"
    : variant === "danger"  ? "btn-danger"
    : "";
  const sizeClass = size === "sm" ? "btn-sm" : "";

  return (
    <button
      className={`btn ${variantClass} ${sizeClass} ${className}`.trim()}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <span
          style={{
            width: 14,
            height: 14,
            border: "2px solid currentColor",
            borderTopColor: "transparent",
            borderRadius: "50%",
            display: "inline-block",
            animation: "spin 0.7s linear infinite",
            flexShrink: 0,
          }}
        />
      ) : icon ? (
        <span style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>{icon}</span>
      ) : null}
      {children}
    </button>
  );
}
