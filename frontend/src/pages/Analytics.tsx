import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getVectorStats, rebuildVectorIndex, searchPapers, vectorSearch } from "../api/papers";
import { PAPER_SOURCES } from "../types/paper";
import type { PaperSource, SearchType, VectorSearchResult } from "../types/paper";

export default function Analytics() {
  const [query, setQuery] = useState("nickel superalloy creep");
  const [source, setSource] = useState<PaperSource | "all">("all");
  const [fullTextOnly, setFullTextOnly] = useState(false);
  const [limit, setLimit] = useState(15);

  const [searchType, setSearchType] = useState<SearchType>("vector");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [results, setResults] = useState<VectorSearchResult[]>([]);
  const [vectorStats, setVectorStats] = useState<{
    count: number;
    available: boolean;
    embedding_model?: string | null;
    embedding_available?: boolean;
  } | null>(null);

  useEffect(() => {
    loadVectorStats();
  }, []);

  const sources = useMemo<PaperSource[]>(
    () => (source === "all" ? [...PAPER_SOURCES] : [source]),
    [source]
  );

  const loadVectorStats = async () => {
    try {
      const stats = await getVectorStats();
      setVectorStats(stats);
    } catch {
      // non-blocking
    }
  };

  const runSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      if (searchType === "text") {
        const res = await searchPapers({
          query,
          sources,
          fullTextOnly,
          limit,
        });
        setResults(res.papers.map((paper) => ({ paper, similarity: 0 })));
        setTotal(res.total);
      } else {
        const res = await vectorSearch({
          query,
          limit,
          source,
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          searchType,
        });
        setResults(res.results);
        setTotal(res.total);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const onRebuildIndex = async () => {
    if (!window.confirm("Перестроить векторный индекс? Это может занять несколько минут.")) return;
    setLoading(true);
    setError(null);
    try {
      const res = await rebuildVectorIndex();
      alert(`Индекс перестроен: ${res.indexed} из ${res.total} статей.`);
      await loadVectorStats();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const getSimilarityColor = (similarity: number) => {
    if (similarity >= 0.8) return { color: "#22c55e" };
    if (similarity >= 0.6) return { color: "#eab308" };
    if (similarity >= 0.4) return { color: "#f97316" };
    return { color: "#ef4444" };
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>Поиск</h2>
        <div className="actions">
          <button className="btn" onClick={onRebuildIndex} disabled={loading}>
            Перестроить индекс
          </button>
          <button className="btn btn-primary" onClick={runSearch} disabled={loading}>
            {loading ? "Поиск..." : "Искать"}
          </button>
        </div>
      </div>

      {vectorStats && (
        <div className="panel">
          <h3>Статус векторного индекса</h3>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div>
              <strong>Статей в индексе:</strong> {vectorStats.count}
            </div>
            <div>
              <strong>Модель:</strong> <span className="muted">{vectorStats.embedding_model || "не указана"}</span>
            </div>
            <div>
              <strong>Эмбеддинги:</strong>{" "}
              <span style={{ color: vectorStats.embedding_available ? "#22c55e" : "#ef4444" }}>
                {vectorStats.embedding_available ? "доступны" : "недоступны"}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="panel">
        <h3>Параметры поиска</h3>
        <div className="filters">
          <input
            className="input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Введите запрос"
            style={{ minWidth: 420 }}
          />
          <select value={source} onChange={(e) => setSource(e.target.value as PaperSource | "all")}>
            <option value="all">Все источники</option>
            {PAPER_SOURCES.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>
          <select value={searchType} onChange={(e) => setSearchType(e.target.value as SearchType)}>
            <option value="vector">Векторный</option>
            <option value="semantic">Семантический</option>
            <option value="hybrid">Гибридный</option>
            <option value="text">Текстовый</option>
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={fullTextOnly} onChange={(e) => setFullTextOnly(e.target.checked)} />
            Статьи только с полным текстом
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>с:</span>
            <input className="input" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>по:</span>
            <input className="input" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>лимит:</span>
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              style={{ width: 90 }}
            />
          </label>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && !results.length && <p className="muted">Поиск...</p>}

      <div className="panel">
        <h3>
          Результаты <span className="muted">(найдено: {total})</span>
        </h3>
        {results.length === 0 ? (
          <p className="muted">Нет результатов. Введите запрос и нажмите «Искать».</p>
        ) : (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Название</th>
                <th>Сходство</th>
                <th>Источник</th>
                <th>Дата</th>
                <th>DOI</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {results.map((res) => (
                <tr key={res.paper.id}>
                  <td>{res.paper.id}</td>
                  <td style={{ maxWidth: 520 }}>
                    <div style={{ fontWeight: 700 }}>{res.paper.title}</div>
                    <div className="muted" style={{ marginTop: 4 }}>
                      {(res.paper.keywords ?? []).slice(0, 5).join(", ")}
                    </div>
                  </td>
                  <td>
                    <span style={{ fontWeight: 600, ...getSimilarityColor(res.similarity) }}>
                      {searchType === "text" ? "—" : `${(res.similarity * 100).toFixed(0)}%`}
                    </span>
                  </td>
                  <td>{res.paper.source}</td>
                  <td>{res.paper.publicationDate ? res.paper.publicationDate.slice(0, 10) : "—"}</td>
                  <td>{res.paper.doi ?? "—"}</td>
                  <td>
                    <Link className="action-link" to={`/papers/${res.paper.id}`}>
                      Открыть
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

