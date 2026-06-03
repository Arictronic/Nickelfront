import { useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fullTextSearch, getSearchSuggestions } from "../api/papers";
import {
  getProcessingProgress,
  getProcessingStatusKey,
  getProcessingStatusLabel,
  PAPER_SOURCES,
} from "../types/paper";
import type {
  FullTextSearchResult,
  FullTextSearchStats,
  PaperSource,
} from "../types/paper";

type SearchMode = "plain" | "phrase" | "websearch";

const SEARCH_MODES: Array<{ value: SearchMode; label: string; description: string }> = [
  {
    value: "websearch",
    label: "Расширенный",
    description: "операторы AND / OR / NOT и фразы в кавычках",
  },
  {
    value: "plain",
    label: "Обычный",
    description: "все слова запроса должны встречаться в индексе",
  },
  {
    value: "phrase",
    label: "Точная фраза",
    description: "поиск выражения как цельного фрагмента через phraseto_tsquery",
  },
];

const MODE_EXAMPLES: Record<SearchMode, string> = {
  plain: "nickel superalloy creep",
  phrase: "high temperature oxidation",
  websearch: 'nickel AND superalloy "high temperature" NOT iron',
};

const MATCH_FIELD_LABELS: Record<string, string> = {
  title: "заголовок",
  abstract: "аннотация",
  full_text: "полный текст",
};

function normalizeLimit(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 20;
  return Math.max(1, Math.min(100, Math.floor(parsed)));
}

function normalizePage(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.floor(parsed));
}

function normalizeMode(value: string | null): SearchMode {
  return value === "plain" || value === "phrase" || value === "websearch"
    ? value
    : "websearch";
}

function normalizeSource(value: string | null): PaperSource | "all" {
  if (!value || value === "all") return "all";
  return PAPER_SOURCES.includes(value as PaperSource) ? (value as PaperSource) : "all";
}

function getErrorMessage(error: unknown) {
  const responseDetail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof responseDetail === "string") return responseDetail;
  if (error instanceof Error && error.message) return error.message;
  return "Не удалось выполнить полнотекстовый поиск";
}

function formatDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : "—";
}

function hasPdf(paper: FullTextSearchResult) {
  return paper.hasPdf || Boolean(paper.pdfUrl || paper.pdfLocalPath);
}

function hasExtractedText(paper: FullTextSearchResult) {
  return paper.hasFullText || Boolean(paper.fullText?.trim());
}

function isFullTextIndexed(paper: FullTextSearchResult) {
  return paper.fullTextIndexed || hasExtractedText(paper);
}

function getStatusTone(status: string | null | undefined) {
  const key = getProcessingStatusKey(status);
  if (!key) return "unknown";
  if (["ready", "ready_with_fallback", "completed"].includes(key)) {
    return "success";
  }
  if (["failed", "markdown_failed", "pdf_download_failed", "keywords_failed", "qwen_auth_failed"].includes(key)) {
    return "error";
  }
  if (["pending", "queued_for_content_processing", "pdf_pending"].includes(key)) {
    return "pending";
  }
  return "processing";
}

function stripMarkTags(value: string) {
  return value.replace(/<\/?mark>/gi, "");
}

function renderHighlightedText(value: string | null | undefined): ReactNode {
  if (!value) return null;
  const parts = value.split(/(<mark>.*?<\/mark>)/gis).filter(Boolean);
  if (!parts.length) return value;

  return parts.map((part, index) => {
    const isMarked = /^<mark>.*<\/mark>$/is.test(part);
    const text = stripMarkTags(part);
    return isMarked ? <mark key={`${text}-${index}`}>{text}</mark> : text;
  });
}

function getSnippetKind(paper: FullTextSearchResult) {
  if (paper.fullTextHighlight) return "Фрагмент полного текста";
  if (paper.abstractHighlight || paper.abstract) return "Аннотация";
  return "Фрагмент";
}

export default function FullTextSearch() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [searchMode, setSearchMode] = useState<SearchMode>(normalizeMode(searchParams.get("mode")));
  const [source, setSource] = useState<PaperSource | "all">(normalizeSource(searchParams.get("source")));
  const [limit, setLimit] = useState(normalizeLimit(searchParams.get("limit") ?? 20));
  const [page, setPage] = useState(normalizePage(searchParams.get("page") ?? 1));

  const [results, setResults] = useState<FullTextSearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [stats, setStats] = useState<FullTextSearchStats | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const activeMode = SEARCH_MODES.find((mode) => mode.value === searchMode) ?? SEARCH_MODES[0];

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }

    let active = true;
    const timer = window.setTimeout(() => {
      getSearchSuggestions(trimmed, 7)
        .then((items) => {
          if (!active) return;
          setSuggestions(items);
          setShowSuggestions(items.length > 0);
        })
        .catch(() => {
          if (!active) return;
          setSuggestions([]);
        });
    }, 250);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    const initialQuery = searchParams.get("q")?.trim();
    if (!initialQuery) return;
    void runSearch({
      nextQuery: initialQuery,
      nextMode: normalizeMode(searchParams.get("mode")),
      nextSource: normalizeSource(searchParams.get("source")),
      nextLimit: normalizeLimit(searchParams.get("limit") ?? 20),
      nextPage: normalizePage(searchParams.get("page") ?? 1),
      syncUrl: false,
    });

  }, []);

  const resultInsights = useMemo(() => {
    const sources = new Set<string>();
    let withPdf = 0;
    let withExtractedText = 0;
    let indexed = 0;
    let ready = 0;

    for (const paper of results) {
      sources.add(paper.source);
      if (hasPdf(paper)) withPdf += 1;
      if (hasExtractedText(paper)) withExtractedText += 1;
      if (isFullTextIndexed(paper)) indexed += 1;
      if (["ready", "ready_with_fallback", "completed"].includes(getProcessingStatusKey(paper.processingStatus))) {
        ready += 1;
      }
    }

    return {
      sources: sources.size,
      withPdf,
      withExtractedText,
      indexed,
      ready,
    };
  }, [results]);

  async function runSearch(args?: {
    nextQuery?: string;
    nextMode?: SearchMode;
    nextSource?: PaperSource | "all";
    nextLimit?: number;
    nextPage?: number;
    syncUrl?: boolean;
  }) {
    const effectiveQuery = (args?.nextQuery ?? query).trim();
    const effectiveMode = args?.nextMode ?? searchMode;
    const effectiveSource = args?.nextSource ?? source;
    const effectiveLimit = normalizeLimit(args?.nextLimit ?? limit);
    const effectivePage = normalizePage(args?.nextPage ?? 1);
    const offset = (effectivePage - 1) * effectiveLimit;

    if (!effectiveQuery) {
      setError("Введите поисковый запрос");
      return;
    }

    setLoading(true);
    setError(null);
    setSearched(true);
    setQuery(effectiveQuery);
    setSearchMode(effectiveMode);
    setSource(effectiveSource);
    setLimit(effectiveLimit);
    setPage(effectivePage);
    setShowSuggestions(false);

    if (args?.syncUrl !== false) {
      setSearchParams({
        q: effectiveQuery,
        mode: effectiveMode,
        source: effectiveSource,
        limit: String(effectiveLimit),
        page: String(effectivePage),
      });
    }

    try {
      const response = await fullTextSearch({
        query: effectiveQuery,
        limit: effectiveLimit,
        offset,
        source: effectiveSource === "all" ? undefined : effectiveSource,
        searchMode: effectiveMode,
      });
      setResults(response.papers);
      setTotal(response.total);
      setStats(response.stats);
    } catch (searchError) {
      setError(getErrorMessage(searchError));
      setResults([]);
      setTotal(0);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      void runSearch({ nextPage: 1 });
    }
  }

  function selectSuggestion(suggestion: string) {
    void runSearch({ nextQuery: suggestion, nextPage: 1 });
  }

  function goToPage(nextPage: number) {
    void runSearch({ nextPage: Math.max(1, Math.min(totalPages, nextPage)) });
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Полнотекстовый поиск</h2>
          <p className="page-subtitle">
            Поиск по заголовкам, аннотациям, ключевым словам и извлечённому полному тексту через PostgreSQL FTS.
          </p>
        </div>
        <div className="actions">
          <Link className="btn" to="/search">
            Векторный / гибридный поиск
          </Link>
          <button
            className="btn btn-primary"
            onClick={() => void runSearch({ nextPage: 1 })}
            disabled={loading || !query.trim()}
          >
            {loading ? "Поиск..." : "Искать"}
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Запрос и режим</h3>
        <div style={{ position: "relative" }}>
          <input
            className="input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => query.trim().length >= 2 && suggestions.length > 0 && setShowSuggestions(true)}
            onBlur={() => window.setTimeout(() => setShowSuggestions(false), 180)}
            placeholder="Например: nickel superalloy creep resistance"
            style={{ width: "100%", fontSize: 16, padding: "12px 16px" }}
          />

          {showSuggestions && suggestions.length > 0 && (
            <div
              style={{
                position: "absolute",
                top: "calc(100% + 6px)",
                left: 0,
                right: 0,
                zIndex: 20,
                overflow: "hidden",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                background: "var(--surface)",
                boxShadow: "var(--shadow-md)",
              }}
            >
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectSuggestion(suggestion)}
                  style={{
                    display: "block",
                    width: "100%",
                    padding: "10px 14px",
                    border: 0,
                    borderBottom: "1px solid var(--border)",
                    background: "transparent",
                    color: "var(--text)",
                    cursor: "pointer",
                    textAlign: "left",
                    fontFamily: "var(--font-body)",
                  }}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="filters" style={{ marginTop: 16 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="muted">Режим</span>
            <select
              value={searchMode}
              onChange={(event) => setSearchMode(event.target.value as SearchMode)}
            >
              {SEARCH_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="muted">Источник</span>
            <select
              value={source}
              onChange={(event) => setSource(event.target.value as PaperSource | "all")}
            >
              <option value="all">Все источники</option>
              {PAPER_SOURCES.map((paperSource) => (
                <option key={paperSource} value={paperSource}>
                  {paperSource}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="muted">Результатов на странице</span>
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              value={limit}
              onChange={(event) => setLimit(normalizeLimit(event.target.value))}
              style={{ width: 120 }}
            />
          </label>
        </div>

        <div
          style={{
            marginTop: 16,
            padding: 12,
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            background: "var(--surface-2)",
            color: "var(--muted)",
            fontSize: 13,
          }}
        >
          <strong style={{ color: "var(--text)" }}>{activeMode.label}:</strong> {activeMode.description}. Пример:{" "}
          <code>{MODE_EXAMPLES[searchMode]}</code>
        </div>
      </div>

      {(searched || stats) && (
        <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
          <article className="panel kpi-card">
            <h3>Найдено</h3>
            <p className="kpi">{total}</p>
          </article>
          <article className="panel kpi-card">
            <h3>На странице</h3>
            <p className="kpi">{results.length}</p>
          </article>
          <article className="panel kpi-card">
            <h3>PDF есть</h3>
            <p className="kpi">{resultInsights.withPdf}</p>
          </article>
          <article className="panel kpi-card">
            <h3>Текст извлечён</h3>
            <p className="kpi">{resultInsights.withExtractedText}</p>
          </article>
          <article className="panel kpi-card">
            <h3>Проиндексировано</h3>
            <p className="kpi">{resultInsights.indexed}</p>
          </article>
          <article className="panel kpi-card">
            <h3>Средняя релевантность</h3>
            <p className="kpi">
              {stats ? `${(stats.avg_relevance * 100).toFixed(1)}%` : "—"}
            </p>
          </article>
        </div>
      )}

      {error && (
        <div className="panel">
          <p className="error" style={{ margin: 0 }}>{error}</p>
        </div>
      )}

      <div className="panel">
        <div className="page-head" style={{ alignItems: "flex-start" }}>
          <div>
            <h3>Результаты</h3>
            <p className="muted" style={{ margin: 0 }}>
              {searched
                ? `Страница ${page} из ${totalPages}. Источников в выдаче: ${resultInsights.sources}, готовых к анализу: ${resultInsights.ready}.`
                : "Введите запрос и нажмите «Искать»."}
            </p>
          </div>
          {searched && total > limit && (
            <div className="actions-inline">
              <button onClick={() => goToPage(page - 1)} disabled={loading || page <= 1}>
                Назад
              </button>
              <button onClick={() => goToPage(page + 1)} disabled={loading || page >= totalPages}>
                Вперёд
              </button>
            </div>
          )}
        </div>

        {loading && results.length === 0 && <p className="muted">Идёт поиск...</p>}

        {!loading && searched && results.length === 0 && (
          <p className="muted">По запросу «{query}» ничего не найдено.</p>
        )}

        {results.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16 }}>
            {results.map((paper) => {
              const statusTone = getStatusTone(paper.processingStatus);
              const progress = getProcessingProgress(paper.processingStatus);
              const snippet = paper.fullTextHighlight || paper.abstractHighlight || paper.snippet || paper.abstract;
              const matchedLabels = paper.matchedFields
                .map((field) => MATCH_FIELD_LABELS[field] ?? field)
                .join(", ");

              return (
                <article
                  key={paper.id}
                  className="section-card"
                  style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 16 }}
                >
                  <div style={{ minWidth: 0 }}>
                    <h4 style={{ margin: "0 0 8px", fontSize: 17 }}>
                      <Link to={`/papers/${paper.id}`} style={{ color: "var(--primary)", textDecoration: "none" }}>
                        {renderHighlightedText(paper.titleHighlight) || paper.title || `Статья #${paper.id}`}
                      </Link>
                    </h4>

                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 8 }}>
                      <span className="status-pill neutral">{paper.source}</span>
                      <span className="status-pill neutral">{formatDate(paper.publicationDate)}</span>
                      <span className={`status-pill ${hasPdf(paper) ? "success" : "warning"}`}>
                        {hasPdf(paper) ? "PDF есть" : "PDF нет"}
                      </span>
                      <span className={`status-pill ${hasExtractedText(paper) ? "success" : "warning"}`}>
                        {hasExtractedText(paper) ? "Текст извлечён" : "Текст не извлечён"}
                      </span>
                      <span className={`status-pill ${isFullTextIndexed(paper) ? "success" : "warning"}`}>
                        {isFullTextIndexed(paper) ? "Проиндексировано" : "Не проиндексировано"}
                      </span>
                      <span className={`status-pill ${statusTone}`}>
                        {getProcessingStatusLabel(paper.processingStatus)}
                      </span>
                    </div>

                    {paper.authors.length > 0 && (
                      <p className="muted" style={{ margin: "0 0 8px" }}>
                        <strong>Авторы:</strong> {paper.authors.slice(0, 5).join(", ")}
                        {paper.authors.length > 5 ? ` и ещё ${paper.authors.length - 5}` : ""}
                      </p>
                    )}

                    <p className="muted" style={{ margin: "0 0 8px" }}>
                      <strong>Журнал:</strong> {paper.journal || "—"} {paper.doi ? ` · DOI: ${paper.doi}` : ""}
                    </p>

                    {matchedLabels && (
                      <p className="muted" style={{ margin: "0 0 8px" }}>
                        <strong>Совпадение:</strong> {matchedLabels}. Ранг: {(paper.rank * 100).toFixed(2)}%
                      </p>
                    )}

                    {snippet && (
                      <div
                        style={{
                          margin: "8px 0",
                          color: "var(--text-2)",
                          lineHeight: 1.55,
                        }}
                      >
                        <div className="muted" style={{ marginBottom: 4, fontSize: 12 }}>
                          {getSnippetKind(paper)}
                        </div>
                        <p style={{ margin: 0 }}>{renderHighlightedText(snippet)}</p>
                      </div>
                    )}

                    {paper.keywords.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                        {paper.keywords.slice(0, 10).map((keyword) => (
                          <button
                            key={keyword}
                            type="button"
                            className="status-pill neutral"
                            onClick={() => {
                              setQuery((current) => `${current.trim()} ${keyword}`.trim());
                            }}
                            title="Добавить термин в запрос"
                            style={{ cursor: "pointer" }}
                          >
                            {keyword}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <div style={{ minWidth: 190 }}>
                    <div className="paper-progress">
                      <div className="paper-progress-head">
                        <span>Обработка</span>
                        <span>{progress}%</span>
                      </div>
                      <div className="paper-progress-track">
                        <div
                          className={`paper-progress-fill ${statusTone === "success" ? "done" : statusTone === "error" ? "failed" : ""}`}
                          style={{ width: `${Math.max(3, progress)}%` }}
                        />
                      </div>
                    </div>
                    <Link className="action-link" to={`/papers/${paper.id}`} style={{ marginTop: 12 }}>
                      Открыть карточку
                    </Link>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>

      <div className="panel">
        <h3>Справка</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>
          {SEARCH_MODES.map((mode) => (
            <div key={mode.value}>
              <h4 style={{ margin: "0 0 8px" }}>{mode.label}</h4>
              <p className="muted" style={{ margin: 0 }}>{mode.description}.</p>
              <p className="muted" style={{ margin: "6px 0 0" }}>
                Пример: <code>{MODE_EXAMPLES[mode.value]}</code>
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
