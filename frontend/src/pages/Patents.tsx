import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Pagination from "../components/ui/Pagination";
import type { Paper, PaperListFilters, PaperSource } from "../types/paper";
import { deletePaper, getPapersCount, getPapersList, searchPapers } from "../api/papers";

type SortState = {
  sortKey: "createdAt" | "publicationDate";
  sortDir: "asc" | "desc";
};

const LS_SELECTED = "selectedPapers.v1";

function loadSelected(): number[] {
  try {
    const raw = localStorage.getItem(LS_SELECTED);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as number[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveSelected(ids: number[]) {
  localStorage.setItem(LS_SELECTED, JSON.stringify(ids));
}

export default function Patents() {
  const pageSize = 10;

  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortState>({ sortKey: "createdAt", sortDir: "desc" });

  const [filters, setFilters] = useState<PaperListFilters>({
    source: "all",
    fullTextOnly: false,
    dateFrom: "",
    dateTo: "",
    query: "",
  });

  const [papers, setPapers] = useState<Paper[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<number[]>(() => loadSelected());

  useEffect(() => {
    saveSelected(selectedIds);
  }, [selectedIds]);

  const clientSideFiltersEnabled = Boolean(filters.query || filters.fullTextOnly || filters.dateFrom || filters.dateTo);

  const sourcesForSearch = useMemo<PaperSource[]>(
    () => (filters.source && filters.source !== "all" ? [filters.source] : ["CORE", "arXiv"]),
    [filters.source]
  );

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      if (!clientSideFiltersEnabled) {
        const src = (filters.source ?? "all") as PaperListFilters["source"];
        const count = await getPapersCount(src === "all" ? "all" : (src as PaperSource));
        const offset = (page - 1) * pageSize;
        const items = await getPapersList({ limit: pageSize, offset, source: src });
        setTotalCount(count);
        setPapers(items);
        return;
      }

      // Client-side filtering mode: fetch up to N items, then apply filters in browser.
      // Backend validation: PaperSearchRequest.limit has max=100
      const clientLimit = 100;
      let items: Paper[] = [];

      if (filters.query) {
        const res = await searchPapers({
          query: filters.query,
          sources: sourcesForSearch,
          fullTextOnly: filters.fullTextOnly,
          limit: clientLimit,
        });
        items = res.papers;
      } else {
        const src = (filters.source ?? "all") as PaperListFilters["source"];
        items = await getPapersList({ limit: clientLimit, offset: 0, source: src });
        if (filters.fullTextOnly) {
          items = items.filter((p) => Boolean(p.fullText && p.fullText.trim().length > 0));
        }
      }

      const dateFrom = filters.dateFrom ? filters.dateFrom.slice(0, 10) : "";
      const dateTo = filters.dateTo ? filters.dateTo.slice(0, 10) : "";

      if (dateFrom) {
        items = items.filter((p) => (p.publicationDate ?? "").slice(0, 10) >= dateFrom);
      }
      if (dateTo) {
        items = items.filter((p) => (p.publicationDate ?? "").slice(0, 10) <= dateTo);
      }

      setTotalCount(items.length);
      setPapers(items);
      setPage(1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData().catch(() => null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, filters.source, filters.query, filters.fullTextOnly, filters.dateFrom, filters.dateTo, sort]);

  const sortedPapers = useMemo(() => {
    const copy = [...papers];
    copy.sort((a, b) => {
      const left = sort.sortKey === "createdAt" ? a.createdAt : a.publicationDate;
      const right = sort.sortKey === "createdAt" ? b.createdAt : b.publicationDate;
      const leftV = left ?? "";
      const rightV = right ?? "";
      const cmp = leftV.localeCompare(rightV);
      return sort.sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [papers, sort]);

  const currentIds = sortedPapers.map((p) => p.id);
  const allChecked = currentIds.length > 0 && currentIds.every((id) => selectedIds.includes(id));

  const toggleOne = (id: number) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const toggleAllCurrent = () => {
    if (allChecked) {
      setSelectedIds((prev) => prev.filter((id) => !currentIds.includes(id)));
      return;
    }
    setSelectedIds((prev) => Array.from(new Set([...prev, ...currentIds])));
  };

  const deleteByIds = async (ids: number[]) => {
    if (ids.length === 0) return;
    if (!window.confirm(`Удалить ${ids.length} статей из базы?`)) return;
    await Promise.all(
      ids.map(async (id) => {
        await deletePaper(id);
      })
    );
    setSelectedIds((prev) => prev.filter((id) => !ids.includes(id)));
    await fetchData();
  };

  const exportCSV = () => {
    const ids = selectedIds.filter((id) => currentIds.includes(id));
    if (ids.length === 0) {
      alert("Выберите элементы на текущей странице для экспорта.");
      return;
    }
    const rows = sortedPapers.filter((p) => ids.includes(p.id));
    const csvHeader = ["id", "title", "source", "publicationDate", "doi", "journal", "authors", "keywords", "fullText"];
    const csv = [
      csvHeader.join(","),
      ...rows.map((p) => {
        const row = [
          p.id,
          p.title,
          p.source,
          p.publicationDate ?? "",
          p.doi ?? "",
          p.journal ?? "",
          (p.authors ?? []).join("; "),
          (p.keywords ?? []).join("; "),
          p.fullText ? "yes" : "no",
        ];
        return row.map((x) => `"${String(x).replaceAll('"', '""')}"`).join(",");
      }),
    ].join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "papers.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const paginationEnabled = !clientSideFiltersEnabled;

  return (
    <div className="page">
      <div className="page-head">
        <h2>Статьи (papers)</h2>
        <div className="counter-badge">Всего: {totalCount}</div>
      </div>

      <div className="panel">
        <h3>Фильтры</h3>
        <div className="filters">
          <input
            className="input"
            value={filters.query ?? ""}
            onChange={(e) => setFilters((s) => ({ ...s, query: e.target.value }))}
            placeholder="Поиск по title/abstract/keywords"
          />
          <select
            value={filters.source ?? "all"}
            onChange={(e) => setFilters((s) => ({ ...s, source: e.target.value as PaperListFilters["source"] }))}
          >
            <option value="all">Все источники</option>
            <option value="CORE">CORE</option>
            <option value="arXiv">arXiv</option>
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={filters.fullTextOnly}
              onChange={(e) => setFilters((s) => ({ ...s, fullTextOnly: e.target.checked }))}
            />
            Только с full text
          </label>
          <input type="date" value={filters.dateFrom ?? ""} onChange={(e) => setFilters((s) => ({ ...s, dateFrom: e.target.value }))} />
          <input type="date" value={filters.dateTo ?? ""} onChange={(e) => setFilters((s) => ({ ...s, dateTo: e.target.value }))} />
          {!paginationEnabled && <span className="muted">Фильтры применяются на клиенте, пагинация отключена.</span>}
        </div>
      </div>

      <div className="panel">
        <h3>Сортировка</h3>
        <div className="filters">
          <select value={sort.sortKey} onChange={(e) => setSort((s) => ({ ...s, sortKey: e.target.value as SortState["sortKey"] }))}>
            <option value="createdAt">По created_at</option>
            <option value="publicationDate">По publication_date</option>
          </select>
          <select value={sort.sortDir} onChange={(e) => setSort((s) => ({ ...s, sortDir: e.target.value as SortState["sortDir"] }))}>
            <option value="desc">desc</option>
            <option value="asc">asc</option>
          </select>
        </div>
      </div>

      <div className="actions">
        <button className="btn btn-primary" onClick={exportCSV}>
          Экспорт CSV (текущая выборка)
        </button>
        <button className="btn btn-danger" onClick={() => deleteByIds(selectedIds)}>
          Удалить выбранные
        </button>
      </div>

      {loading && <p className="muted">Загрузка...</p>}
      {error && <p className="error">{error}</p>}

      <table className="table">
        <thead>
          <tr>
            <th>
              <input type="checkbox" checked={allChecked} onChange={toggleAllCurrent} />
            </th>
            <th>ID</th>
            <th>Название</th>
            <th>Авторы</th>
            <th>Источник</th>
            <th>Дата</th>
            <th>DOI</th>
            <th>Full text</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          {sortedPapers.length === 0 ? (
            <tr>
              <td colSpan={9} className="muted">
                Нет результатов.
              </td>
            </tr>
          ) : (
            sortedPapers.map((p) => {
              const checked = selectedIds.includes(p.id);
              return (
                <tr key={p.id}>
                  <td>
                    <input type="checkbox" checked={checked} onChange={() => toggleOne(p.id)} />
                  </td>
                  <td>{p.id}</td>
                  <td style={{ maxWidth: 520 }}>
                    <div style={{ fontWeight: 700 }}>{p.title}</div>
                  </td>
                  <td>{p.authors.slice(0, 2).join(", ")}{p.authors.length > 2 ? "…" : ""}</td>
                  <td>{p.source}</td>
                  <td>{p.publicationDate ? p.publicationDate.slice(0, 10) : "—"}</td>
                  <td>{p.doi ?? "—"}</td>
                  <td>{p.fullText ? "Да" : "Нет"}</td>
                  <td className="actions-inline">
                    <Link className="action-link" to={`/papers/${p.id}`}>
                      Открыть
                    </Link>
                    <button type="button" className="btn" onClick={() => deleteByIds([p.id])}>
                      Удалить
                    </button>
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>

      {paginationEnabled && (
        <Pagination page={page} totalPages={totalPages} onChange={setPage} />
      )}
    </div>
  );
}
