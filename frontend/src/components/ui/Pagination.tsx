export default function Pagination({
  page,
  totalPages,
  onChange,
}: {
  page: number;
  totalPages: number;
  onChange: (p: number) => void;
}) {
  const pages = Array.from({ length: totalPages }, (_, i) => i + 1);
  return (
    <div className="pagination">
      <button className="btn" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        Назад
      </button>
      {pages.map((p) => (
        <button key={p} className={`btn ${p === page ? "btn-primary" : ""}`} onClick={() => onChange(p)}>
          {p}
        </button>
      ))}
      <button className="btn" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
        Вперёд
      </button>
    </div>
  );
}
