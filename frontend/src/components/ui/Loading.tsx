interface LoadingProps {
  text?: string;
  size?: "sm" | "md" | "lg";
}

export default function Loading({ text = "Загрузка...", size = "md" }: LoadingProps) {
  const spinnerSize = size === "sm" ? 16 : size === "lg" ? 32 : 22;
  return (
    <div className="loading-block">
      <span
        className="spinner"
        style={{ width: spinnerSize, height: spinnerSize }}
        aria-label="Загрузка"
      />
      {text && <span>{text}</span>}
    </div>
  );
}

export function LoadingSkeleton({ lines = 3, height = 16 }: { lines?: number; height?: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{
            height,
            width: i === lines - 1 ? "60%" : "100%",
            borderRadius: "var(--radius-sm)",
          }}
        />
      ))}
    </div>
  );
}
