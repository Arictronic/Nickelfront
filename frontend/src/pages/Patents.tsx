import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { deletePaper, getPapersCount, getPapersList, searchPapers } from "../api/papers";
import Pagination from "../components/ui/Pagination";
import { useToast } from "../components/ui/Toast";
import { getProcessingStatusLabel, PAPER_SOURCES } from "../types/paper";
import type { Paper, PaperListFilters, PaperSource } from "../types/paper";

type SortState = {
  sortKey: "id" | "authors" | "createdAt" | "publicationDate";
  sortDir: "asc" | "desc";
};

const LS_SELECTED = "selectedPapers.v1";

const RU = {
  pageTitle: "\u0421\u0442\u0430\u0442\u044c\u0438",
  filters: "\u0424\u0438\u043b\u044c\u0442\u0440\u044b",
  allSources: "\u0412\u0441\u0435 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438",
  queryPlaceholder: "\u041f\u043e\u0438\u0441\u043a \u043f\u043e title/abstract/keywords",
  fullTextOnly: "\u0421\u0442\u0430\u0442\u044c\u0438 \u0442\u043e\u043b\u044c\u043a\u043e \u0441 \u043f\u043e\u043b\u043d\u044b\u043c \u0442\u0435\u043a\u0441\u0442\u043e\u043c",
  from: "\u0441:",
  to: "\u043f\u043e:",
  statusAll: "\u041f\u043e \u0441\u0442\u0430\u0442\u0443\u0441\u0443: \u0432\u0441\u0435",
  clientFiltersNote: "\u0424\u0438\u043b\u044c\u0442\u0440\u044b \u043f\u0440\u0438\u043c\u0435\u043d\u044f\u044e\u0442\u0441\u044f \u043d\u0430 \u043a\u043b\u0438\u0435\u043d\u0442\u0435, \u043f\u0430\u0433\u0438\u043d\u0430\u0446\u0438\u044f \u043e\u0442\u043a\u043b\u044e\u0447\u0435\u043d\u0430.",
  sorting: "\u0421\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u043a\u0430",
  sortById: "\u041f\u043e ID",
  sortByAuthors: "\u041f\u043e \u0430\u0432\u0442\u043e\u0440\u0430\u043c",
  sortByCreated: "\u041f\u043e \u0434\u0430\u0442\u0435 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0438\u044f",
  sortByPublication: "\u041f\u043e \u0434\u0430\u0442\u0435 \u043f\u0443\u0431\u043b\u0438\u043a\u0430\u0446\u0438\u0438",
  sortDesc: "\u041f\u043e \u0443\u0431\u044b\u0432\u0430\u043d\u0438\u044e",
  sortAsc: "\u041f\u043e \u0432\u043e\u0437\u0440\u0430\u0441\u0442\u0430\u043d\u0438\u044e",
  exportCsv: "\u042d\u043a\u0441\u043f\u043e\u0440\u0442 CSV",
  deleteSelected: "\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u044b\u0435",
  total: "\u0412\u0441\u0435\u0433\u043e",
  loading: "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430...",
  noResults: "\u041d\u0435\u0442 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u043e\u0432.",
  colTitle: "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435",
  colAuthors: "\u0410\u0432\u0442\u043e\u0440\u044b",
  colSource: "\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a",
  colDate: "\u0414\u0430\u0442\u0430",
  colStatus: "\u0421\u0442\u0430\u0442\u0443\u0441",
  colActions: "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044f",
  yes: "\u0414\u0430",
  no: "\u041d\u0435\u0442",
  open: "\u041e\u0442\u043a\u0440\u044b\u0442\u044c",
  del: "\u0423\u0434\u0430\u043b\u0438\u0442\u044c",
  dash: "\u2014",
  confirmDelete: (n: number) => `\u0423\u0434\u0430\u043b\u0438\u0442\u044c ${n} \u0441\u0442\u0430\u0442\u0435\u0439 \u0438\u0437 \u0431\u0430\u0437\u044b?`,
  deletedOk: (n: number) => `\u0423\u0434\u0430\u043b\u0435\u043d\u043e ${n} \u0441\u0442\u0430\u0442\u0435\u0439`,
  deleteError: "\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u0438",
  pickForExport: "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u044d\u043b\u0435\u043c\u0435\u043d\u0442\u044b \u043d\u0430 \u0442\u0435\u043a\u0443\u0449\u0435\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435 \u0434\u043b\u044f \u044d\u043a\u0441\u043f\u043e\u0440\u0442\u0430.",
} as const;

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
  const toast = useToast();
  const hasFullTextOrPdf = (p: Paper) =>
    Boolean((p.fullText && p.fullText.trim().length > 0) || p.pdfUrl || p.pdfLocalPath);

  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortState>({ sortKey: "createdAt", sortDir: "desc" });
  const [filters, setFilters] = useState<PaperListFilters>({
    source: "all",
    fullTextOnly: false,
    dateFrom: "",
    dateTo: "",
    query: "",
    processingStatus: "all",
  });
  const [papers, setPapers] = useState<Paper[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>(() => loadSelected());

  useEffect(() => {
    saveSelected(selectedIds);
  }, [selectedIds]);

  const clientSideFiltersEnabled = Boolean(
    filters.query ||
      filters.fullTextOnly ||
      filters.dateFrom ||
      filters.dateTo ||
      (filters.processingStatus && filters.processingStatus !== "all")
  );

  const sourcesForSearch = useMemo<PaperSource[]>(
    () => (filters.source && filters.source !== "all" ? [filters.source] : [...PAPER_SOURCES]),
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

      let items: Paper[] = [];
      if (filters.query) {
        const res = await searchPapers({
          query: filters.query,
          sources: sourcesForSearch,
          fullTextOnly: filters.fullTextOnly,
          limit: 100,
        });
        items = res.papers;
      } else {
        const src = (filters.source ?? "all") as PaperListFilters["source"];
        items = await getPapersList({ limit: 100, offset: 0, source: src });
        if (filters.fullTextOnly) items = items.filter(hasFullTextOrPdf);
      }

      const dateFrom = filters.dateFrom ? filters.dateFrom.slice(0, 10) : "";
      const dateTo = filters.dateTo ? filters.dateTo.slice(0, 10) : "";
      if (dateFrom) items = items.filter((p) => (p.publicationDate ?? "").slice(0, 10) >= dateFrom);
      if (dateTo) items = items.filter((p) => (p.publicationDate ?? "").slice(0, 10) <= dateTo);
      if (filters.processingStatus && filters.processingStatus !== "all") {
        items = items.filter((p) => p.processingStatus === filters.processingStatus);
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
  }, [page, filters.source, filters.query, filters.fullTextOnly, filters.dateFrom, filters.dateTo, filters.processingStatus, sort]);

  const sortedPapers = useMemo(() => {
    const copy = [...papers];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sort.sortKey === "id") cmp = a.id - b.id;
      else if (sort.sortKey === "authors") {
        const left = (a.authors?.[0] ?? "").toLowerCase();
        const right = (b.authors?.[0] ?? "").toLowerCase();
        cmp = left.localeCompare(right);
      } else {
        const left = sort.sortKey === "createdAt" ? a.createdAt : a.publicationDate;
        const right = sort.sortKey === "createdAt" ? b.createdAt : b.publicationDate;
        cmp = (left ?? "").localeCompare(right ?? "");
      }
      return sort.sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [papers, sort]);

  const statusOptions = useMemo(() => {
    const unique = Array.from(new Set(papers.map((p) => p.processingStatus).filter(Boolean)));
    return unique.sort((a, b) => getProcessingStatusLabel(a).localeCompare(getProcessingStatusLabel(b)));
  }, [papers]);

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
    if (!window.confirm(RU.confirmDelete(ids.length))) return;
    try {
      await Promise.all(ids.map((id) => deletePaper(id)));
      setSelectedIds((prev) => prev.filter((id) => !ids.includes(id)));
      toast.success(RU.deletedOk(ids.length));
      await fetchData();
    } catch {
      toast.error(RU.deleteError);
    }
  };

  const exportCSV = () => {
    const ids = selectedIds.filter((id) => currentIds.includes(id));
    if (ids.length === 0) {
      alert(RU.pickForExport);
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
          hasFullTextOrPdf(p) ? "yes" : "no",
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
        <h2>{RU.pageTitle}</h2>
      </div>

      <div className="panel">
        <h3>{RU.filters}</h3>
        <div className="filters">
          <input
            className="input"
            style={{ minWidth: 540 }}
            value={filters.query ?? ""}
            onChange={(e) => setFilters((s) => ({ ...s, query: e.target.value }))}
            placeholder={RU.queryPlaceholder}
          />
          <select value={filters.source ?? "all"} onChange={(e) => setFilters((s) => ({ ...s, source: e.target.value as PaperListFilters["source"] }))}>
            <option value="all">{RU.allSources}</option>
            {PAPER_SOURCES.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={filters.fullTextOnly} onChange={(e) => setFilters((s) => ({ ...s, fullTextOnly: e.target.checked }))} />
            {RU.fullTextOnly}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>{RU.from}</span>
            <input type="date" value={filters.dateFrom ?? ""} onChange={(e) => setFilters((s) => ({ ...s, dateFrom: e.target.value }))} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>{RU.to}</span>
            <input type="date" value={filters.dateTo ?? ""} onChange={(e) => setFilters((s) => ({ ...s, dateTo: e.target.value }))} />
          </label>
          <select value={filters.processingStatus ?? "all"} onChange={(e) => setFilters((s) => ({ ...s, processingStatus: e.target.value }))}>
            <option value="all">{RU.statusAll}</option>
            {statusOptions.map((st) => (
              <option key={st} value={st}>
                {getProcessingStatusLabel(st)}
              </option>
            ))}
          </select>
          {!paginationEnabled && <span className="muted">{RU.clientFiltersNote}</span>}
        </div>
      </div>

      <div className="panel">
        <h3>{RU.sorting}</h3>
        <div className="filters">
          <select value={sort.sortKey} onChange={(e) => setSort((s) => ({ ...s, sortKey: e.target.value as SortState["sortKey"] }))}>
            <option value="id">{RU.sortById}</option>
            <option value="authors">{RU.sortByAuthors}</option>
            <option value="createdAt">{RU.sortByCreated}</option>
            <option value="publicationDate">{RU.sortByPublication}</option>
          </select>
          <select value={sort.sortDir} onChange={(e) => setSort((s) => ({ ...s, sortDir: e.target.value as SortState["sortDir"] }))}>
            <option value="desc">{RU.sortDesc}</option>
            <option value="asc">{RU.sortAsc}</option>
          </select>
        </div>
      </div>

      <div className="actions">
        <button className="btn btn-primary" onClick={exportCSV}>
          {RU.exportCsv}
        </button>
        <button className="btn btn-danger" onClick={() => deleteByIds(selectedIds)}>
          {RU.deleteSelected}
        </button>
        <div className="counter-badge" style={{ marginLeft: "auto" }}>
          {RU.total}: {totalCount}
        </div>
      </div>

      {loading && <p className="muted">{RU.loading}</p>}
      {error && <p className="error">{error}</p>}

      <table className="table">
        <thead>
          <tr>
            <th>
              <input type="checkbox" checked={allChecked} onChange={toggleAllCurrent} />
            </th>
            <th>ID</th>
            <th>{RU.colTitle}</th>
            <th>{RU.colAuthors}</th>
            <th>{RU.colSource}</th>
            <th>{RU.colDate}</th>
            <th>DOI</th>
            <th>Full text</th>
            <th>{RU.colStatus}</th>
            <th>{RU.colActions}</th>
          </tr>
        </thead>
        <tbody>
          {sortedPapers.length === 0 ? (
            <tr>
              <td colSpan={10} className="muted">
                {RU.noResults}
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
                  <td>
                    {p.authors.slice(0, 2).join(", ")}
                    {p.authors.length > 2 ? "..." : ""}
                  </td>
                  <td>{p.source}</td>
                  <td>{p.publicationDate ? p.publicationDate.slice(0, 10) : RU.dash}</td>
                  <td>{p.doi ?? RU.dash}</td>
                  <td>{hasFullTextOrPdf(p) ? RU.yes : RU.no}</td>
                  <td>{getProcessingStatusLabel(p.processingStatus)}</td>
                  <td>
                    <div className="actions-inline">
                      <Link className="action-link" to={`/papers/${p.id}`}>
                        {RU.open}
                      </Link>
                      <button type="button" className="btn" onClick={() => deleteByIds([p.id])}>
                        {RU.del}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>

      {paginationEnabled && <Pagination page={page} totalPages={totalPages} onChange={setPage} />}
    </div>
  );
}

