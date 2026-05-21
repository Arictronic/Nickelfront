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
    <div className="pagination">
      <button className="btn" disabled={safePage <= 1} onClick={() => onChange(safePage - 1)}>
        Назад
      </button>
      {pages.map((p) =>
        typeof p === "number" ? (
          <button key={p} className={`btn ${p === safePage ? "btn-primary" : ""}`} onClick={() => onChange(p)}>
            {p}
          </button>
        ) : (
          <span key={p} className="muted" style={{ padding: "0 4px" }}>
            ...
          </span>
        )
      )}
      <button className="btn" disabled={safePage >= safeTotal} onClick={() => onChange(safePage + 1)}>
        Вперёд
      </button>
    </div>
  );
}
