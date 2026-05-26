import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../api/client";
import {
  fullTextSearch,
  getVectorStats,
  rebuildVectorIndex,
  vectorSearch,
} from "../api/papers";
import { useAuthStore } from "../store/authStore";
import { PAPER_SOURCES } from "../types/paper";
import type {
  PaperSource,
  SearchType,
  VectorSearchResult,
} from "../types/paper";

type TopItem = {
  name: string;
  count: number;
};

function normalizeLimit(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.min(100, Math.floor(parsed)));
}

export default function Analytics() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.is_admin;

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
  const [keywordHints, setKeywordHints] = useState<TopItem[]>([]);
  const [hintsExpanded, setHintsExpanded] = useState(false);
  const [vectorStats, setVectorStats] = useState<{
    count: number;
    available: boolean;
    embedding_model?: string | null;
    embedding_available?: boolean;
  } | null>(null);

  useEffect(() => {
    loadVectorStats();
    loadKeywordHints();
  }, []);

  const loadVectorStats = async () => {
    try {
      const stats = await getVectorStats();
      setVectorStats(stats);
    } catch {
      // non-blocking
    }
  };

  const loadKeywordHints = async () => {
    try {
      const { data } = await apiClient.get<{ items: TopItem[] }>(
        "/analytics/metrics/top?item_type=keywords&limit=100",
      );
      setKeywordHints(data.items ?? []);
    } catch {
      // non-blocking
    }
  };

  const runSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const normalizedLimit = normalizeLimit(limit);
      setLimit(normalizedLimit);

      if (searchType === "text") {
        const res = await fullTextSearch({
          query,
          source: source === "all" ? undefined : source,
          limit: normalizedLimit,
          searchMode: "websearch",
        });
        const papers = fullTextOnly
          ? res.papers.filter((paper) => paper.hasFullText || Boolean(paper.fullText?.trim()))
          : res.papers;
        setResults(papers.map((paper) => ({ paper, similarity: -1 })));
        setTotal(fullTextOnly ? papers.length : res.total);
      } else {
        const res = await vectorSearch({
          query,
          limit: normalizedLimit,
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
    if (
      !window.confirm(
        "Перестроить векторный индекс? Это может занять несколько минут.",
      )
    )
      return;
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

  const resultInsights = useMemo(() => {
    const sourcesMap = new Map<string, number>();
    const keywordSet = new Set<string>();
    let similaritySum = 0;

    for (const result of results) {
      sourcesMap.set(
        result.paper.source,
        (sourcesMap.get(result.paper.source) ?? 0) + 1,
      );
      similaritySum += result.similarity || 0;
      for (const keyword of result.paper.keywords ?? []) {
        const normalized = keyword.trim().toLowerCase();
        if (normalized) keywordSet.add(normalized);
      }
    }

    return {
      sourceCount: sourcesMap.size,
      topSource: Array.from(sourcesMap.entries()).sort(
        (a, b) => b[1] - a[1],
      )[0],
      uniqueKeywords: keywordSet.size,
      avgSimilarity: results.length ? similaritySum / results.length : 0,
    };
  }, [results]);

  const visibleHints = hintsExpanded ? keywordHints : keywordHints.slice(0, 24);
  const dateFiltersAvailable = searchType !== "text";

  return (
    <div className="page">
      <div className="page-head">
        <h2>Поиск</h2>
        <div className="actions">
          <Link className="btn" to="/fulltext-search">
            Полнотекстовый поиск
          </Link>
          {isAdmin && (
            <button className="btn" onClick={onRebuildIndex} disabled={loading}>
              Перестроить индекс
            </button>
          )}
          <button
            className="btn btn-primary"
            onClick={runSearch}
            disabled={loading}
          >
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
              <strong>Модель:</strong>{" "}
              <span className="muted">
                {vectorStats.embedding_model || "не указана"}
              </span>
            </div>
            <div>
              <strong>Эмбеддинги:</strong>{" "}
              <span
                style={{
                  color: vectorStats.embedding_available
                    ? "#22c55e"
                    : "#ef4444",
                }}
              >
                {vectorStats.embedding_available ? "доступны" : "недоступны"}
              </span>
            </div>
          </div>
        </div>
      )}

      {keywordHints.length > 0 && (
        <div className="panel">
          <h3>Подсказки по терминам для поиска</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {visibleHints.map((item) => (
              <button
                key={item.name}
                className="btn"
                style={{ padding: "7px 10px", fontSize: 12 }}
                onClick={() =>
                  setQuery((current) =>
                    current.trim()
                      ? `${current.trim()} ${item.name}`
                      : item.name,
                  )
                }
                title={`Встречается: ${item.count}`}
              >
                {item.name} <span className="muted">{item.count}</span>
              </button>
            ))}
          </div>
          {keywordHints.length > 24 && (
            <button
              className="btn"
              style={{ marginTop: 12 }}
              onClick={() => setHintsExpanded((v) => !v)}
            >
              {hintsExpanded ? "Свернуть" : "Развернуть дальше"}
            </button>
          )}
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
          <select
            value={source}
            onChange={(e) => setSource(e.target.value as PaperSource | "all")}
          >
            <option value="all">Все источники</option>
            {PAPER_SOURCES.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>
          <select
            value={searchType}
            onChange={(e) => setSearchType(e.target.value as SearchType)}
          >
            <option value="vector">Векторный</option>
            <option value="semantic">Семантический</option>
            <option value="hybrid">Гибридный</option>
            <option value="text">Полнотекстовый</option>
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={fullTextOnly}
              onChange={(e) => setFullTextOnly(e.target.checked)}
            />
            Только с полным текстом
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>с:</span>
            <input
              className="input"
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              disabled={!dateFiltersAvailable}
              title={
                dateFiltersAvailable
                  ? undefined
                  : "Фильтр дат для полнотекстового режима доступен на отдельной странице через уточнение источника и запроса"
              }
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>по:</span>
            <input
              className="input"
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              disabled={!dateFiltersAvailable}
              title={
                dateFiltersAvailable
                  ? undefined
                  : "Фильтр дат для полнотекстового режима доступен на отдельной странице через уточнение источника и запроса"
              }
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>лимит:</span>
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              value={limit}
              onChange={(e) => setLimit(normalizeLimit(e.target.value))}
              style={{ width: 90 }}
            />
          </label>
        </div>
        {!dateFiltersAvailable && (
          <p className="muted" style={{ marginTop: 10 }}>
            Фильтр дат отключён для встроенного полнотекстового режима. Для расширенного поиска используйте отдельную страницу. {" "}
            <Link className="action-link" to={`/fulltext-search?q=${encodeURIComponent(query)}`}>
              Открыть полнотекстовый поиск
            </Link>
          </p>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {loading && !results.length && <p className="muted">Поиск...</p>}

      <div className="panel">
        <h3>
          Результаты <span className="muted">(найдено: {total})</span>
        </h3>
        {results.length > 0 && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: 12,
              marginBottom: 14,
            }}
          >
            <div>
              <p className="muted">Источников в выдаче</p>
              <p className="kpi-status">{resultInsights.sourceCount}</p>
            </div>
            <div>
              <p className="muted">Главный источник</p>
              <p className="kpi-status">
                {resultInsights.topSource
                  ? `${resultInsights.topSource[0]} (${resultInsights.topSource[1]})`
                  : "нет"}
              </p>
            </div>
            <div>
              <p className="muted">Keywords в найденных</p>
              <p className="kpi-status">{resultInsights.uniqueKeywords}</p>
            </div>
            <div>
              <p className="muted">Среднее сходство</p>
              <p className="kpi-status">
                {searchType === "text"
                  ? "полнотекстовый"
                  : `${(resultInsights.avgSimilarity * 100).toFixed(0)}%`}
              </p>
            </div>
          </div>
        )}
        {results.length === 0 ? (
          <p className="muted">
            Нет результатов. Введите запрос и нажмите «Искать».
          </p>
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
                    <span
                      style={{
                        fontWeight: 600,
                        ...(searchType === "text" ? {} : getSimilarityColor(res.similarity)),
                      }}
                    >
                      {searchType === "text"
                        ? "Полнотекстовый"
                        : `${(res.similarity * 100).toFixed(0)}%`}
                    </span>
                  </td>
                  <td>{res.paper.source}</td>
                  <td>
                    {res.paper.publicationDate
                      ? res.paper.publicationDate.slice(0, 10)
                      : "—"}
                  </td>
                  <td>{res.paper.doi ?? "—"}</td>
                  <td>
                    <Link
                      className="action-link"
                      to={`/papers/${res.paper.id}`}
                    >
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
