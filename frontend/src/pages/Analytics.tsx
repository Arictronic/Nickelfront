import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { searchPapers, vectorSearch, getVectorStats, rebuildVectorIndex } from "../api/papers";
import { PAPER_SOURCES } from "../types/paper";
import type { PaperSource, SearchType } from "../types/paper";
import type { Paper, VectorSearchResult } from "../types/paper";

export default function Analytics() {
  // Search query state
  const [query, setQuery] = useState("nickel superalloy creep");
  const [source, setSource] = useState<PaperSource | "all">("all");
  const [fullTextOnly, setFullTextOnly] = useState(false);
  const [limit, setLimit] = useState(15);
  
  // Vector search settings
  const [searchType, setSearchType] = useState<SearchType>("vector");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [vectorResults, setVectorResults] = useState<VectorSearchResult[]>([]);
  
  // Vector stats
  const [vectorStats, setVectorStats] = useState<{
    count: number;
    available: boolean;
    embedding_model?: string | null;
    embedding_available?: boolean;
  } | null>(null);

  useEffect(() => {
    // Load vector stats on mount
    loadVectorStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadVectorStats = async () => {
    try {
      const stats = await getVectorStats();
      setVectorStats(stats);
    } catch (e) {
      console.error("Failed to load vector stats:", e);
    }
  };

  const sources = useMemo<PaperSource[]>(
    () => (source === "all" ? [...PAPER_SOURCES] : [source]),
    [source]
  );

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      if (searchType === "text") {
        // Fallback to text search
        const res = await searchPapers({
          query,
          sources,
          fullTextOnly,
          limit,
        });
        setVectorResults(res.papers.map(p => ({ paper: p, similarity: 0 })));
        setTotal(res.total);
      } else {
        // Vector search
        const res = await vectorSearch({
          query,
          limit,
          source,
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          searchType,
        });
        setVectorResults(res.results);
        setTotal(res.total);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleRebuildIndex = async () => {
    if (!confirm("Перестроить векторный индекс? Это может занять несколько минут.")) return;
    
    try {
      setLoading(true);
      const result = await rebuildVectorIndex();
      alert(`Векторный индекс перестроен: ${result.indexed} из ${result.total} статей`);
      loadVectorStats();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const getSimilarityColor = (similarity: number) => {
    if (similarity >= 0.8) return { color: "#22c55e" }; // green
    if (similarity >= 0.6) return { color: "#eab308" }; // yellow
    if (similarity >= 0.4) return { color: "#f97316" }; // orange
    return { color: "#ef4444" }; // red
  };

  const getSimilarityLabel = (similarity: number) => {
    if (similarity >= 0.8) return "Высокое";
    if (similarity >= 0.6) return "Среднее";
    if (similarity >= 0.4) return "Низкое";
    return "Слабое";
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>🔍 Векторный поиск статей</h2>
        <div className="actions">
          <button className="btn btn-secondary" onClick={handleRebuildIndex} disabled={loading}>
            Перестроить индекс
          </button>
          <button className="btn btn-primary" onClick={() => run()} disabled={loading}>
            {loading ? "Поиск..." : "Искать"}
          </button>
        </div>
      </div>

      {/* Vector Stats Info */}
      {vectorStats && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3>📊 Статус векторного поиска</h3>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div>
              <strong>Статей в индексе:</strong>{" "}
              <span style={{ color: vectorStats.count > 0 ? "#22c55e" : "#ef4444" }}>
                {vectorStats.count}
              </span>
            </div>
            <div>
              <strong>Модель:</strong>{" "}
              <span className="muted">{vectorStats.embedding_model || "Не доступна"}</span>
            </div>
            <div>
              <strong>Эмбеддинги:</strong>{" "}
              <span style={{ color: vectorStats.embedding_available ? "#22c55e" : "#ef4444" }}>
                {vectorStats.embedding_available ? "Доступны" : "Не доступны"}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Search Settings */}
      <div className="panel">
        <h3>⚙️ Настройки поиска</h3>
        <div className="filters" style={{ display: "grid", gap: 12 }}>
          {/* Query & Source */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <input
              className="input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Введите запрос"
              style={{ minWidth: 380 }}
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
              <option value="text">Текстовый (fallback)</option>
            </select>
          </div>
          
          {/* Date filters & options */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted">Дата от:</span>
              <input
                className="input"
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                style={{ width: 150 }}
              />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted">До:</span>
              <input
                className="input"
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                style={{ width: 150 }}
              />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={fullTextOnly}
                onChange={(e) => setFullTextOnly(e.target.checked)}
              />
              Только с full text
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted">Лимит:</span>
              <input
                className="input"
                type="number"
                min={1}
                max={100}
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                style={{ width: 80 }}
              />
            </label>
          </div>
          
          {/* Search type description */}
          <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
            {searchType === "vector" && "📌 Векторный поиск по семантическому сходству (ChromaDB)"}
            {searchType === "semantic" && "📌 Семантический поиск с фильтрацией по метаданным"}
            {searchType === "hybrid" && "📌 Гибридный поиск: комбинация векторного и текстового"}
            {searchType === "text" && "📌 Обычный текстовый поиск (fallback если эмбеддинги недоступны)"}
          </div>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && !vectorResults.length && <p className="muted">Поиск...</p>}

      {/* Results */}
      <div className="panel">
        <h3>
          📄 Результаты{" "}
          <span className="muted" style={{ fontSize: 14 }}>
            (Найдено: {total})
          </span>
        </h3>
        
        {vectorResults.length === 0 ? (
          <p className="muted">Нет результатов. Введите запрос и нажмите "Искать".</p>
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
              {vectorResults.map((result) => (
                <tr key={result.paper.id}>
                  <td>{result.paper.id}</td>
                  <td style={{ maxWidth: 520 }}>
                    <div style={{ fontWeight: 700 }}>{result.paper.title}</div>
                    <div className="muted" style={{ marginTop: 4 }}>
                      {(result.paper.keywords ?? []).slice(0, 5).join(", ")}
                    </div>
                  </td>
                  <td>
                    <span style={{ fontWeight: 600, ...getSimilarityColor(result.similarity) }}>
                      {(result.similarity * 100).toFixed(0)}%
                    </span>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {getSimilarityLabel(result.similarity)}
                    </div>
                  </td>
                  <td>{result.paper.source}</td>
                  <td>{result.paper.publicationDate ? result.paper.publicationDate.slice(0, 10) : "—"}</td>
                  <td>{result.paper.doi ?? "—"}</td>
                  <td>
                    <Link className="action-link" to={`/papers/${result.paper.id}`}>
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
