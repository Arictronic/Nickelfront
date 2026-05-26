type PageItem = number | "dots-left" | "dots-right";

function buildPages(page: number, totalPages: number): PageItem[] {
  if (totalPages <= 9) return Array.from({ length: totalPages }, (_, i) => i + 1);

  const pages = new Set<number>([1, totalPages]);
  const start = Math.max(2, page - 2);
  const end = Math.min(totalPages - 1, page + 2);
  for (let p = start; p <= end; p += 1) pages.add(p);

  const sorted = Array.from(pages).sort((a, b) => a - b);
  const result: PageItem[] = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const current = sorted[i];
    const previous = sorted[i - 1];
    if (i > 0 && current - previous > 1) {
      result.push(previous === 1 ? "dots-left" : "dots-right");
    }
    result.push(current);
  }
  return result;
}

export default function Pagination({
  page,
  totalPages,
  onChange,
}: {
  page: number;
  totalPages: number;
  onChange: (p: number) => void;
}) {
  const safeTotal = Math.max(1, totalPages);
  const safePage = Math.min(Math.max(1, page), safeTotal);
  const pages = buildPages(safePage, safeTotal);

  return (
    <div
      className="pagination"
      style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}
    >
      <button
        className="btn btn-sm"
        disabled={safePage <= 1}
        onClick={() => onChange(safePage - 1)}
        aria-label="Предыдущая страница"
      >
        ←
      </button>

      {pages.map((p) =>
        typeof p === "number" ? (
          <button
            key={p}
            className={`btn btn-sm${p === safePage ? " btn-primary" : ""}`}
            onClick={() => onChange(p)}
            aria-current={p === safePage ? "page" : undefined}
          >
            {p}
          </button>
        ) : (
          <span
            key={p}
            className="muted"
            style={{ padding: "0 2px", fontSize: 13 }}
          >
            …
          </span>
        )
      )}

      <button
        className="btn btn-sm"
        disabled={safePage >= safeTotal}
        onClick={() => onChange(safePage + 1)}
        aria-label="Следующая страница"
      >
        →
      </button>

      <span className="muted" style={{ fontSize: 12, marginLeft: 4 }}>
        {safePage} / {safeTotal}
      </span>
    </div>
  );
}
