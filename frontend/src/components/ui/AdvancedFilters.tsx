import { useState, useMemo } from "react";
import type { PaperSource } from "../../types/paper";

interface AdvancedFiltersProps {
  onFilterChange: (filters: FilterState) => void;
  initialFilters?: FilterState;
  sources?: PaperSource[];
}

export interface FilterState {
  query: string;
  sources: PaperSource[];
  dateFrom: string;
  dateTo: string;
  hasAbstract: boolean;
  hasFullText: boolean;
  hasKeywords: boolean;
  authorsQuery: string;
  journalQuery: string;
  sortBy: "date" | "relevance" | "title";
  sortOrder: "asc" | "desc";
}

const defaultFilters: FilterState = {
  query: "",
  sources: [],
  dateFrom: "",
  dateTo: "",
  hasAbstract: false,
  hasFullText: false,
  hasKeywords: false,
  authorsQuery: "",
  journalQuery: "",
  sortBy: "date",
  sortOrder: "desc",
};

/**
 * Компонент расширенных фильтров для статей.
 */
export default function AdvancedFilters({
  onFilterChange,
  initialFilters = defaultFilters,
  sources = ["CORE", "arXiv"],
}: AdvancedFiltersProps) {
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const updateFilter = <K extends keyof FilterState>(
    key: K,
    value: FilterState[K]
  ) => {
    const newFilters = { ...filters, [key]: value };
    setFilters(newFilters);
    onFilterChange(newFilters);
  };

  const toggleSource = (source: PaperSource) => {
    const newSources = filters.sources.includes(source)
      ? filters.sources.filter((s) => s !== source)
      : [...filters.sources, source];
    updateFilter("sources", newSources);
  };

  const clearFilters = () => {
    setFilters(defaultFilters);
    onFilterChange(defaultFilters);
  };

  const hasActiveFilters = useMemo(() => {
    return (
      filters.query !== "" ||
      filters.sources.length > 0 ||
      filters.dateFrom !== "" ||
      filters.dateTo !== "" ||
      filters.hasAbstract ||
      filters.hasFullText ||
      filters.hasKeywords ||
      filters.authorsQuery !== "" ||
      filters.journalQuery !== ""
    );
  }, [filters]);

  return (
    <div className="advanced-filters" style={{ marginBottom: 16 }}>
      {/* Basic filters row */}
      <div className="filters" style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <input
          className="input"
          type="text"
          placeholder="Поиск по названию..."
          value={filters.query}
          onChange={(e) => updateFilter("query", e.target.value)}
          style={{ flex: 1, minWidth: 200 }}
        />

        <select
          value={filters.sortBy}
          onChange={(e) => updateFilter("sortBy", e.target.value as any)}
          style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid #d1d5db" }}
        >
          <option value="date">По дате</option>
          <option value="relevance">По релевантности</option>
          <option value="title">По названию</option>
        </select>

        <select
          value={filters.sortOrder}
          onChange={(e) => updateFilter("sortOrder", e.target.value as any)}
          style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid #d1d5db" }}
        >
          <option value="desc">↓ По убыванию</option>
          <option value="asc">↑ По возрастанию</option>
        </select>

        <button
          className="btn"
          onClick={() => setShowAdvanced(!showAdvanced)}
          type="button"
        >
          {showAdvanced ? "▼ Скрыть" : "▶ Дополнительно"}
        </button>

        {hasActiveFilters && (
          <button className="btn btn-danger" onClick={clearFilters} type="button">
            ✕ Сбросить
          </button>
        )}
      </div>

      {/* Advanced filters */}
      {showAdvanced && (
        <div
          className="advanced-filters-panel"
          style={{
            marginTop: 12,
            padding: 16,
            background: "#f8fafc",
            borderRadius: 8,
            border: "1px solid #e2e8f0",
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16 }}>
            {/* Источники */}
            <div>
              <label style={{ display: "block", marginBottom: 8, fontWeight: 500 }}>
                Источники
              </label>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {sources.map((source) => (
                  <label key={source} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input
                      type="checkbox"
                      checked={filters.sources.includes(source)}
                      onChange={() => toggleSource(source)}
                    />
                    <span>{source}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Диапазон дат */}
            <div>
              <label style={{ display: "block", marginBottom: 8, fontWeight: 500 }}>
                Диапазон дат
              </label>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <input
                  className="input"
                  type="date"
                  value={filters.dateFrom}
                  onChange={(e) => updateFilter("dateFrom", e.target.value)}
                  placeholder="С даты"
                />
                <input
                  className="input"
                  type="date"
                  value={filters.dateTo}
                  onChange={(e) => updateFilter("dateTo", e.target.value)}
                  placeholder="По дату"
                />
              </div>
            </div>

            {/* Наличие полей */}
            <div>
              <label style={{ display: "block", marginBottom: 8, fontWeight: 500 }}>
                Наличие полей
              </label>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={filters.hasAbstract}
                    onChange={(e) => updateFilter("hasAbstract", e.target.checked)}
                  />
                  <span>С аннотацией</span>
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={filters.hasFullText}
                    onChange={(e) => updateFilter("hasFullText", e.target.checked)}
                  />
                  <span>С полным текстом</span>
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={filters.hasKeywords}
                    onChange={(e) => updateFilter("hasKeywords", e.target.checked)}
                  />
                  <span>С ключевыми словами</span>
                </label>
              </div>
            </div>

            {/* Авторы */}
            <div>
              <label style={{ display: "block", marginBottom: 8, fontWeight: 500 }}>
                Авторы
              </label>
              <input
                className="input"
                type="text"
                placeholder="Имя автора..."
                value={filters.authorsQuery}
                onChange={(e) => updateFilter("authorsQuery", e.target.value)}
              />
            </div>

            {/* Журнал */}
            <div>
              <label style={{ display: "block", marginBottom: 8, fontWeight: 500 }}>
                Журнал
              </label>
              <input
                className="input"
                type="text"
                placeholder="Название журнала..."
                value={filters.journalQuery}
                onChange={(e) => updateFilter("journalQuery", e.target.value)}
              />
            </div>
          </div>
        </div>
      )}

      {/* Active filters summary */}
      {hasActiveFilters && (
        <div
          style={{
            marginTop: 12,
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
          }}
        >
          {filters.query && (
            <span className="filter-tag" style={{
              padding: "4px 12px",
              background: "#e0e7ff",
              borderRadius: 16,
              fontSize: 13,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}>
              🔍 {filters.query}
              <button
                onClick={() => updateFilter("query", "")}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
              >
                ✕
              </button>
            </span>
          )}

          {filters.sources.map((source) => (
            <span key={source} className="filter-tag" style={{
              padding: "4px 12px",
              background: "#dbeafe",
              borderRadius: 16,
              fontSize: 13,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}>
              📁 {source}
              <button
                onClick={() => toggleSource(source)}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
              >
                ✕
              </button>
            </span>
          ))}

          {filters.dateFrom && (
            <span className="filter-tag" style={{
              padding: "4px 12px",
              background: "#fef3c7",
              borderRadius: 16,
              fontSize: 13,
            }}>
              📅 от {filters.dateFrom}
            </span>
          )}

          {filters.dateTo && (
            <span className="filter-tag" style={{
              padding: "4px 12px",
              background: "#fef3c7",
              borderRadius: 16,
              fontSize: 13,
            }}>
              📅 до {filters.dateTo}
            </span>
          )}

          {filters.hasAbstract && (
            <span className="filter-tag" style={{
              padding: "4px 12px",
              background: "#d1fae5",
              borderRadius: 16,
              fontSize: 13,
            }}>
              ✓ С аннотацией
            </span>
          )}

          {filters.hasFullText && (
            <span className="filter-tag" style={{
              padding: "4px 12px",
              background: "#d1fae5",
              borderRadius: 16,
              fontSize: 13,
            }}>
              ✓ С полным текстом
            </span>
          )}
        </div>
      )}
    </div>
  );
}
