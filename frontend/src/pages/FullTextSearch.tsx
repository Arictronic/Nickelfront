import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { fullTextSearch, getSearchSuggestions, getSearchStats } from "../api/papers";
import type { Paper } from "../types/paper";

type SearchMode = "plain" | "phrase" | "websearch";

export default function FullTextSearch() {
  // Search state
  const [query, setQuery] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("websearch");
  const [source, setSource] = useState<"all" | "CORE" | "arXiv">("all");
  const [limit, setLimit] = useState(20);
  
  // Results state
  const [results, setResults] = useState<Paper[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  
  // Suggestions state
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  
  // Stats state
  const [stats, setStats] = useState<{ total_matches: number; avg_relevance: number; max_relevance: number } | null>(null);
  
  // Error state
  const [error, setError] = useState<string | null>(null);

  // Load suggestions on query change
  useEffect(() => {
    if (query.length >= 2) {
      getSearchSuggestions(query, 5)
        .then(setSuggestions)
        .catch(console.error);
      setShowSuggestions(true);
    } else {
      setSuggestions([]);
      setShowSuggestions(false);
    }
  }, [query]);

  // Search function
  const handleSearch = async () => {
    if (!query.trim()) return;
    
    setLoading(true);
    setError(null);
    setSearched(true);
    
    try {
      const { papers, total: totalCount } = await fullTextSearch({
        query,
        limit,
        source: source === "all" ? undefined : source,
        searchMode,
      });
      
      setResults(papers);
      setTotal(totalCount);
      
      // Load stats
      const statsData = await getSearchStats(query);
      setStats(statsData);
    } catch (e: any) {
      setError(e.message || "Ошибка поиска");
      setResults([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  // Handle key press
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSearch();
    }
  };

  // Select suggestion
  const selectSuggestion = (suggestion: string) => {
    setQuery(suggestion);
    setShowSuggestions(false);
    setTimeout(() => handleSearch(), 0);
  };

  // Search mode examples
  const modeExamples = useMemo(() => ({
    plain: "nickel superalloy (AND между словами)",
    phrase: "high temperature (точная фраза)",
    websearch: 'nickel AND superalloy, "high temperature", nickel NOT iron',
  }), []);

  return (
    <div className="page">
      <div className="page-head">
        <h2>Полнотекстовый поиск</h2>
      </div>

      {/* Search Panel */}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Поисковый запрос</h3>
        
        <div style={{ position: "relative", marginBottom: 16 }}>
          <input
            className="input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyPress={handleKeyPress}
            onFocus={() => query.length >= 2 && setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
            placeholder="Введите поисковый запрос..."
            style={{ width: "100%", fontSize: 16, padding: "12px 16px" }}
          />
          
          {/* Suggestions dropdown */}
          {showSuggestions && suggestions.length > 0 && (
            <div style={{
              position: "absolute",
              top: "100%",
              left: 0,
              right: 0,
              background: "white",
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
              zIndex: 10,
              marginTop: 4,
            }}>
              {suggestions.map((s, idx) => (
                <div
                  key={idx}
                  onClick={() => selectSuggestion(s)}
                  style={{
                    padding: "10px 16px",
                    cursor: "pointer",
                    borderBottom: idx < suggestions.length - 1 ? "1px solid #f3f4f6" : "none",
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.background = "#f9fafb"}
                  onMouseLeave={(e) => e.currentTarget.style.background = "white"}
                >
                  {s}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Search options */}
        <div className="filters" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted">Режим:</span>
              <select 
                value={searchMode} 
                onChange={(e) => setSearchMode(e.target.value as SearchMode)}
                style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid #d1d5db" }}
              >
                <option value="websearch">Расширенный (websearch)</option>
                <option value="plain">Обычный (plain)</option>
                <option value="phrase">Точная фраза (phrase)</option>
              </select>
            </label>

            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted">Источник:</span>
              <select 
                value={source} 
                onChange={(e) => setSource(e.target.value as any)}
                style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid #d1d5db" }}
              >
                <option value="all">Все</option>
                <option value="CORE">CORE</option>
                <option value="arXiv">arXiv</option>
              </select>
            </label>

            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted">Лимит:</span>
              <input
                type="number"
                min={1}
                max={100}
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                style={{ width: 70, padding: "8px 12px", borderRadius: 6, border: "1px solid #d1d5db" }}
              />
            </label>

            <button 
              className="btn btn-primary" 
              onClick={handleSearch}
              disabled={loading || !query.trim()}
            >
              {loading ? "Поиск..." : "🔍 Найти"}
            </button>
          </div>
        </div>

        {/* Mode examples */}
        <div style={{ 
          padding: 12, 
          background: "var(--surface-2)", 
          borderRadius: 8, 
          fontSize: 13,
          border: "1px solid var(--border)",
          color: "var(--muted)",
        }}>
          <strong>Пример запроса ({searchMode}):</strong>{" "}
          <code
            style={{
              background: "var(--bg)",
              color: "var(--text)",
              padding: "2px 6px",
              borderRadius: 4,
              border: "1px solid var(--border)",
            }}
          >
            {modeExamples[searchMode]}
          </code>
        </div>
      </div>

      {/* Stats */}
      {stats && (
        <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          <article className="panel kpi-card">
            <h3>Совпадений</h3>
            <p className="kpi">{stats.total_matches}</p>
          </article>
          <article className="panel kpi-card">
            <h3>Средняя релевантность</h3>
            <p className="kpi">{(stats.avg_relevance * 100).toFixed(2)}%</p>
          </article>
          <article className="panel kpi-card">
            <h3>Макс. релевантность</h3>
            <p className="kpi">{(stats.max_relevance * 100).toFixed(2)}%</p>
          </article>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="panel">
          <p className="error">{error}</p>
        </div>
      )}

      {/* Results */}
      {loading && (
        <div className="panel">
          <p>Поиск...</p>
        </div>
      )}

      {!loading && searched && results.length === 0 && (
        <div className="panel">
          <p className="muted">Ничего не найдено по запросу "{query}"</p>
        </div>
      )}

      {!loading && results.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>
            Результаты ({total} найдено)
          </h3>
          
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {results.map((paper) => (
              <article 
                key={paper.id}
                style={{
                  padding: 16,
                  border: "1px solid #e5e7eb",
                  borderRadius: 8,
                  background: "white",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ flex: 1 }}>
                    <h4 style={{ margin: "0 0 8px", color: "#1e293b" }}>
                      <Link 
                        to={`/papers/${paper.id}`}
                        style={{ color: "#4a6cf7", textDecoration: "none" }}
                      >
                        {paper.title}
                      </Link>
                    </h4>
                    
                    {paper.authors && paper.authors.length > 0 && (
                      <p style={{ margin: "0 0 8px", fontSize: 13, color: "#64748b" }}>
                        <strong>Авторы:</strong> {paper.authors.slice(0, 5).join(", ")}
                        {paper.authors.length > 5 && ` и ещё ${paper.authors.length - 5}`}
                      </p>
                    )}
                    
                    <p style={{ margin: "0 0 8px", fontSize: 14, color: "#475569" }}>
                      <strong>Журнал:</strong> {paper.journal || "—"} | 
                      <strong> Дата:</strong> {paper.publicationDate ? paper.publicationDate.slice(0, 10) : "—"}
                    </p>
                    
                    {paper.abstract && (
                      <p style={{ 
                        margin: "8px 0", 
                        fontSize: 14, 
                        color: "#334155",
                        lineHeight: 1.5,
                        display: "-webkit-box",
                        WebkitLineClamp: 3,
                        WebkitBoxOrient: "vertical",
                        overflow: "hidden",
                      }}>
                        {paper.abstract}
                      </p>
                    )}
                    
                    {paper.keywords && paper.keywords.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                        {paper.keywords.slice(0, 8).map((kw, idx) => (
                          <span
                            key={idx}
                            style={{
                              padding: "4px 8px",
                              background: "#e0e7ff",
                              borderRadius: 12,
                              fontSize: 12,
                              color: "#1e293b",
                            }}
                          >
                            {kw}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  
                  <div style={{ marginLeft: 16, textAlign: "right" }}>
                    <span style={{
                      padding: "4px 8px",
                      background: paper.source === "CORE" ? "#dbeafe" : "#ede9fe",
                      color: paper.source === "CORE" ? "#1e40af" : "#5b21b6",
                      borderRadius: 4,
                      fontSize: 12,
                      fontWeight: 500,
                    }}>
                      {paper.source}
                    </span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      )}

      {/* Help */}
      <div className="panel" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>📖 Справка по поиску</h3>
        
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 16 }}>
          <div>
            <h4 style={{ margin: "0 0 8px" }}>Обычный поиск (plain)</h4>
            <p style={{ fontSize: 14, color: "#64748b", margin: 0 }}>
              Слова соединяются оператором AND. Пример: <code>nickel superalloy</code>
            </p>
          </div>
          
          <div>
            <h4 style={{ margin: "0 0 8px" }}>Точная фраза (phrase)</h4>
            <p style={{ fontSize: 14, color: "#64748b", margin: 0 }}>
              Поиск точной фразы. Пример: <code>"high temperature"</code>
            </p>
          </div>
          
          <div>
            <h4 style={{ margin: "0 0 8px" }}>Расширенный (websearch)</h4>
            <p style={{ fontSize: 14, color: "#64748b", margin: 0 }}>
              Поддержка операторов: <code>AND</code>, <code>OR</code>, <code>NOT</code>, кавычки для фраз
            </p>
            <p style={{ fontSize: 13, color: "#94a3b8", marginTop: 4 }}>
              Пример: <code>nickel AND superalloy, "high temperature", nickel NOT iron</code>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
