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
        <h2>Поиск и аналитика</h2>
      </div>

      {/* Верхние информационные карточки (KPI-стиль как на скриншоте) */}
      {vectorStats && (
        <div className="kpi-grid">
          <div className="panel kpi-card">
            <h3>Статей в индексе</h3>
            <div className="kpi">{vectorStats.count}</div>
          </div>

          <div className="panel kpi-card">
            <h3>Модель эмбеддингов</h3>
            <div className="kpi-status" style={{ fontSize: "14px", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
              {vectorStats.embedding_model || "Не указана"}
            </div>
          </div>

          <div className="panel kpi-card">
            <h3>Статус эмбеддингов</h3>
            <div style={{ marginTop: "12px" }}>
              <span className={`session-status ${vectorStats.embedding_available ? "active" : "inactive"}`}>
                <span className="session-dot"></span>
                {vectorStats.embedding_available ? "Доступны" : "Недоступны"}
              </span>
            </div>
          </div>

          <div className="panel kpi-card" style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "stretch", padding: "16px" }}>
            <h3>Инструменты индекса</h3>
            <button className="btn btn-ghost" onClick={onRebuildIndex} disabled={loading} style={{ width: "100%", fontSize: "12px", padding: "8px" }}>
              Перестроить индекс
            </button>
          </div>
        </div>
      )}

      {/* Переработанная лаконичная структура параметров поиска (всё в одну линию, без хаоса) */}
      <div className="panel">
        <h3>Параметры поиска</h3>
        <div className="filters" style={{ display: "flex", flexWrap: "wrap", gap: "12px", alignItems: "center", background: "transparent", border: "none", padding: 0 }}>
          <input
            className="input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Введите поисковый запрос..."
            style={{ flex: "2 1 300px" }}
          />

          <select className="input" value={source} onChange={(e) => setSource(e.target.value as PaperSource | "all")} style={{ flex: "1 1 150px" }}>
            <option value="all">Все источники</option>
            {PAPER_SOURCES.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>

          <select className="input" value={searchType} onChange={(e) => setSearchType(e.target.value as SearchType)} style={{ flex: "1 1 150px" }}>
            <option value="vector">Векторный поиск</option>
            <option value="semantic">Семантический</option>
            <option value="hybrid">Гибридный</option>
            <option value="text">Текстовый</option>
          </select>

          <div style={{ display: "flex", gap: "8px", alignItems: "center", flex: "1 1 auto" }}>
            <span className="muted" style={{ fontSize: "13px" }}>Период:</span>
            <input className="input" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} style={{ padding: "8px 12px" }} />
            <span className="muted" style={{ fontSize: "13px" }}>—</span>
            <input className="input" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} style={{ padding: "8px 12px" }} />
          </div>

          <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
            <span className="muted" style={{ fontSize: "13px" }}>Лимит:</span>
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              style={{ width: "75px" }}
            />
          </div>

          <label className="checkbox-label" style={{ userSelect: "none", margin: "0 8px" }}>
            <input type="checkbox" checked={fullTextOnly} onChange={(e) => setFullTextOnly(e.target.checked)} />
            <span>Только Full-text</span>
          </label>

          <button className="btn btn-primary" onClick={runSearch} disabled={loading} style={{ padding: "10px 28px", marginLeft: "auto" }}>
            {loading ? "Поиск..." : "Искать"}
          </button>
        </div>
      </div>

      {error && <p className="error" style={{ margin: "0 4px" }}>{error}</p>}
      {loading && !results.length && <p className="muted" style={{ margin: "0 4px" }}>Поток данных загружается...</p>}

      {/* Таблица результатов в стиле Glassmorphism */}
      <div className="panel">
        <h3>
          Результаты выдачи <span className="muted" style={{ textTransform: "none", marginLeft: "6px" }}>({total} документов)</span>
        </h3>
        {results.length === 0 ? (
          <p className="muted" style={{ padding: "12px 0 0" }}>Система готова к поиску. Сформулируйте запрос выше.</p>
        ) : (
          <div style={{ overflowX: "auto", marginTop: "16px" }}>
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: "60px" }}>ID</th>
                  <th>Название и ключевые слова</th>
                  <th style={{ width: "110px" }}>Релевантность</th>
                  <th style={{ width: "120px" }}>Источник</th>
                  <th style={{ width: "110px" }}>Дата</th>
                  <th style={{ width: "140px" }}>DOI</th>
                  <th style={{ width: "90px", textAlign: "right" }}>Действие</th>
                </tr>
              </thead>
              <tbody>
                {results.map((res) => (
                  <tr key={res.paper.id}>
                    <td className="muted" style={{ fontFamily: "monospace" }}>{res.paper.id}</td>
                    <td style={{ maxWidth: "500px" }}>
                      <div style={{ fontWeight: 600, fontSize: "14px", lineHeight: "1.4" }}>{res.paper.title}</div>
                      {res.paper.keywords && res.paper.keywords.length > 0 && (
                        <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginTop: "6px" }}>
                          {res.paper.keywords.slice(0, 4).map((kw, idx) => (
                            <span key={idx} className="counter-badge" style={{ fontSize: "11px", padding: "2px 8px" }}>
                              {kw}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <span style={{ fontWeight: 700, fontSize: "14px", ...getSimilarityColor(res.similarity) }}>
                        {searchType === "text" ? "—" : `${(res.similarity * 100).toFixed(0)}%`}
                      </span>
                    </td>
                    <td>
                      <span className="user-chip" style={{ fontSize: "12px", padding: "4px 10px" }}>{res.paper.source}</span>
                    </td>
                    <td className="muted">{res.paper.publicationDate ? res.paper.publicationDate.slice(0, 10) : "—"}</td>
                    <td className="muted" style={{ fontSize: "13px", fontFamily: "monospace" }}>{res.paper.doi ?? "—"}</td>
                    <td style={{ textAlign: "right" }}>
                      <Link className="action-link" to={`/papers/${res.paper.id}`}>
                        Открыть
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}