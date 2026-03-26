import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { searchPapers } from "../api/papers";
import type { PaperSource } from "../types/paper";
import type { Paper } from "../types/paper";

export default function Analytics() {
  const [query, setQuery] = useState("nickel superalloy creep");
  const [source, setSource] = useState<PaperSource | "all">("all");
  const [fullTextOnly, setFullTextOnly] = useState(false);
  const [limit, setLimit] = useState(15);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [results, setResults] = useState<Paper[]>([]);

  useEffect(() => {
    // initial auto-search for demo
    run().catch(() => null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sources = useMemo<PaperSource[]>(
    () => (source === "all" ? ["CORE", "arXiv"] : [source]),
    [source]
  );

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await searchPapers({
        query,
        sources,
        fullTextOnly,
        limit,
      });
      setResults(res.papers);
      setTotal(res.total);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>Векторный поиск (UI) - пока fallback</h2>
        <div className="actions">
          <button className="btn btn-primary" onClick={() => run()}>
            Искать
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Поиск</h3>
        <div className="filters">
          <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Введите запрос" style={{ minWidth: 380 }} />
          <select value={source} onChange={(e) => setSource(e.target.value as PaperSource | "all")}>
            <option value="all">Все источники</option>
            <option value="CORE">CORE</option>
            <option value="arXiv">arXiv</option>
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={fullTextOnly} onChange={(e) => setFullTextOnly(e.target.checked)} />
            Только с full text
          </label>
          <input className="input" type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(Number(e.target.value))} style={{ width: 120 }} />
          <span className="muted">В бэке сейчас нет endpoint для эмбеддингов, поэтому используем `/papers/search`.</span>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Поиск...</p>}

      <div className="panel">
        <h3>Результаты</h3>
        <div className="muted">Найдено (backend limit): {total}</div>
        <table className="table" style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th>ID</th>
              <th>Название</th>
              <th>Источник</th>
              <th>Дата</th>
              <th>DOI</th>
              <th>Full text</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {results.length === 0 ? (
              <tr>
                <td colSpan={7} className="muted">
                  Нет результатов.
                </td>
              </tr>
            ) : (
              results.map((p) => (
                <tr key={p.id}>
                  <td>{p.id}</td>
                  <td style={{ maxWidth: 520 }}>
                    <div style={{ fontWeight: 700 }}>{p.title}</div>
                    <div className="muted" style={{ marginTop: 4 }}>
                      {(p.keywords ?? []).slice(0, 5).join(", ")}
                    </div>
                  </td>
                  <td>{p.source}</td>
                  <td>{p.publicationDate ? p.publicationDate.slice(0, 10) : "—"}</td>
                  <td>{p.doi ?? "—"}</td>
                  <td>{p.fullText ? "Да" : "Нет"}</td>
                  <td>
                    <Link className="action-link" to={`/papers/${p.id}`}>
                      Открыть
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
