import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { deletePaper, getPapersCount, getPapersList } from "../api/papers";
import Pagination from "../components/ui/Pagination";
import { useToast } from "../components/ui/Toast";
import {
  getProcessingProgress,
  getProcessingStatusKey,
  getProcessingStatusLabel,
  isPaperProcessing,
  PAPER_SOURCES,
} from "../types/paper";
import type { Paper, PaperListFilters, PaperSource } from "../types/paper";

type SortState = {
  sortKey: "id" | "authors" | "createdAt" | "publicationDate";
  sortDir: "asc" | "desc";
};

const LS_SELECTED = "selectedPapers.v1";
const PAGE_SIZE = 10;
const CLIENT_SCAN_LIMIT = 5000;
const CLIENT_SCAN_PAGE_SIZE = 100;
const DEFAULT_SORT: SortState = { sortKey: "createdAt", sortDir: "desc" };

const RU = {
  pageTitle: "Статьи",
  filters: "Фильтры",
  allSources: "Все источники",
  queryPlaceholder: "Поиск по title/abstract/keywords",
  fullTextOnly: "Статьи только с полным текстом",
  from: "с:",
  to: "по:",
  statusAll: "По статусу: все",
  clientFiltersNote: (limit: number, loaded: number, filtered: number) =>
    loaded >= limit
      ? `Загружено ${loaded} записей, после фильтров осталось ${filtered}. Для полной точности по большой базе нужны backend-фильтры.`
      : `Загружено ${loaded} записей, после фильтров осталось ${filtered}.`,
  sorting: "Сортировка",
  sortById: "По ID",
  sortByAuthors: "По авторам",
  sortByCreated: "По дате добавления",
  sortByPublication: "По дате публикации",
  sortDesc: "По убыванию",
  sortAsc: "По возрастанию",
  exportCsv: "Экспорт CSV",
  deleteSelected: "Удалить выбранные",
  total: "Всего",
  loading: "Загрузка...",
  noResults: "Нет результатов.",
  colTitle: "Название",
  colAuthors: "Авторы",
  colSource: "Источник",
  colDate: "Дата",
  colStatus: "Статус",
  colFullText: "Полный текст",
  colActions: "Действия",
  yes: "Да",
  no: "Нет",
  open: "Открыть",
  del: "Удалить",
  dash: "—",
  confirmDelete: (n: number) => `Удалить ${n} статей из базы?`,
  hiddenSelectedIgnored: (n: number) =>
    `Скрытые выбранные записи не будут удалены: ${n}.`,
  deletedOk: (n: number) => `Удалено ${n} статей`,
  deleteError: "Ошибка при удалении",
  pickForExport: "Выберите элементы на текущей странице для экспорта.",
  pickForDelete: "Выберите элементы на текущей странице для удаления.",
} as const;

function loadSelected(): number[] {
  try {
    const raw = localStorage.getItem(LS_SELECTED);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as number[];
    return Array.isArray(parsed)
      ? parsed.filter((id) => Number.isFinite(id))
      : [];
  } catch {
    return [];
  }
}

function clearSelected() {
  localStorage.removeItem(LS_SELECTED);
}

function saveSelected(ids: number[]) {
  localStorage.setItem(LS_SELECTED, JSON.stringify(ids));
}

function hasFullTextOrPdf(p: Paper) {
  return Boolean(
    (p.fullText && p.fullText.trim().length > 0) || p.pdfUrl || p.pdfLocalPath,
  );
}

function isDefaultSort(sort: SortState) {
  return (
    sort.sortKey === DEFAULT_SORT.sortKey &&
    sort.sortDir === DEFAULT_SORT.sortDir
  );
}

const PROCESSING_STATUS_OPTIONS = [
  "pending",
  "queued_for_content_processing",
  "processing_content",
  "started",
  "pdf_pending",
  "downloading_pdf",
  "pdf_downloaded",
  "pdf_download_failed",
  "pdf_unavailable",
  "extracting_pdf_text",
  "pdf_parsed",
  "fulltext_fallback_parsed",
  "fulltext_unavailable",
  "digitizing_file",
  "formatting_markdown",
  "markdown_ready",
  "markdown_failed",
  "markdown_skipped",
  "analyzing_ru",
  "ru_analysis_ready",
  "ru_analysis_fallback",
  "extracting_keywords",
  "keywords_ready",
  "keywords_failed",
  "indexing_vector",
  "embedding_ready",
  "embedding_skipped",
  "ready",
  "ready_with_fallback",
  "completed",
  "failed",
];


function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}

function queryMatchesPaper(paper: Paper, rawQuery: string) {
  const query = rawQuery.trim().toLowerCase();
  if (!query) return true;

  const haystack = [
    paper.title,
    paper.abstract,
    paper.journal,
    paper.doi,
    paper.sourceId,
    paper.source,
    ...(paper.authors ?? []),
    ...(paper.keywords ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return haystack.includes(query);
}

export default function Patents() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
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
  const [loadedCount, setLoadedCount] = useState(0);
  const [filteredCount, setFilteredCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>(() =>
    loadSelected(),
  );
  const debouncedQuery = useDebouncedValue(filters.query ?? "", 450);

  useEffect(() => {
    saveSelected(selectedIds);
  }, [selectedIds]);

  const clientFiltersEnabled = Boolean(
    debouncedQuery ||
    filters.fullTextOnly ||
    filters.dateFrom ||
    filters.dateTo ||
    (filters.processingStatus && filters.processingStatus !== "all"),
  );
  const clientDatasetMode = clientFiltersEnabled || !isDefaultSort(sort);

  useEffect(() => {
    setPage(1);
  }, [
    filters.source,
    debouncedQuery,
    filters.fullTextOnly,
    filters.dateFrom,
    filters.dateTo,
    filters.processingStatus,
    sort.sortKey,
    sort.sortDir,
  ]);

  const loadAllPapersForClientMode = async () => {
    const src = (filters.source ?? "all") as PaperListFilters["source"];
    const expectedTotal = await getPapersCount(
      src === "all" ? "all" : (src as PaperSource),
    );
    const maxToLoad = Math.min(expectedTotal, CLIENT_SCAN_LIMIT);
    const pages: Paper[][] = [];

    for (let offset = 0; offset < maxToLoad; offset += CLIENT_SCAN_PAGE_SIZE) {
      const limit = Math.min(CLIENT_SCAN_PAGE_SIZE, maxToLoad - offset);
      const chunk = await getPapersList({ limit, offset, source: src });
      pages.push(chunk);
      if (chunk.length < limit) break;
    }

    return pages.flat();
  };

  const fetchData = async (showLoading = true) => {
    if (showLoading) setLoading(true);
    setError(null);
    try {
      if (!clientDatasetMode) {
        const src = (filters.source ?? "all") as PaperListFilters["source"];
        const count = await getPapersCount(
          src === "all" ? "all" : (src as PaperSource),
        );
        const offset = (page - 1) * PAGE_SIZE;
        const items = await getPapersList({
          limit: PAGE_SIZE,
          offset,
          source: src,
        });
        setTotalCount(count);
        setLoadedCount(items.length);
        setFilteredCount(items.length);
        setPapers(items);
        if (count === 0) {
          setSelectedIds([]);
          clearSelected();
        }
        return;
      }

      let items = await loadAllPapersForClientMode();
      const loadedTotal = items.length;

      if (debouncedQuery)
        items = items.filter((paper) =>
          queryMatchesPaper(paper, debouncedQuery),
        );
      if (filters.fullTextOnly) items = items.filter(hasFullTextOrPdf);

      const dateFrom = filters.dateFrom ? filters.dateFrom.slice(0, 10) : "";
      const dateTo = filters.dateTo ? filters.dateTo.slice(0, 10) : "";
      if (dateFrom)
        items = items.filter(
          (p) => (p.publicationDate ?? "").slice(0, 10) >= dateFrom,
        );
      if (dateTo)
        items = items.filter(
          (p) => (p.publicationDate ?? "").slice(0, 10) <= dateTo,
        );
      if (filters.processingStatus && filters.processingStatus !== "all") {
        items = items.filter(
          (p) => getProcessingStatusKey(p.processingStatus) === filters.processingStatus,
        );
      }

      const filteredTotal = items.length;
      const pageStart = (page - 1) * PAGE_SIZE;
      const pageItems = items.slice(pageStart, pageStart + PAGE_SIZE);

      setTotalCount(filteredTotal);
      setLoadedCount(loadedTotal);
      setFilteredCount(filteredTotal);
      setPapers(pageItems);
      if (filteredTotal === 0) {
        setSelectedIds([]);
        clearSelected();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    fetchData().catch(() => null);
  }, [
    page,
    filters.source,
    debouncedQuery,
    filters.fullTextOnly,
    filters.dateFrom,
    filters.dateTo,
    filters.processingStatus,
    sort.sortKey,
    sort.sortDir,
  ]);

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
        const left =
          sort.sortKey === "createdAt" ? a.createdAt : a.publicationDate;
        const right =
          sort.sortKey === "createdAt" ? b.createdAt : b.publicationDate;
        cmp = (left ?? "").localeCompare(right ?? "");
      }
      return sort.sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [papers, sort]);

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const visiblePapers = clientDatasetMode
    ? sortedPapers.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
    : sortedPapers;

  const statusOptions = useMemo(() => {
    const fromLoaded = papers
      .map((p) => getProcessingStatusKey(p.processingStatus))
      .filter(Boolean);
    const unique = Array.from(
      new Set([...PROCESSING_STATUS_OPTIONS, ...fromLoaded]),
    );
    return unique.sort((a, b) =>
      getProcessingStatusLabel(a).localeCompare(getProcessingStatusLabel(b)),
    );
  }, [papers]);

  const currentIds = visiblePapers.map((p) => p.id);
  const allChecked =
    currentIds.length > 0 && currentIds.every((id) => selectedIds.includes(id));
  const hasProcessingPapers = visiblePapers.some((p) =>
    isPaperProcessing(p.processingStatus),
  );

  useEffect(() => {
    if (!hasProcessingPapers) return;
    const timer = window.setInterval(() => {
      fetchData(false).catch(() => null);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [
    hasProcessingPapers,
    page,
    filters.source,
    debouncedQuery,
    filters.fullTextOnly,
    filters.dateFrom,
    filters.dateTo,
    filters.processingStatus,
  ]);

  const toggleOne = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const toggleAllCurrent = () => {
    if (allChecked) {
      setSelectedIds((prev) => prev.filter((id) => !currentIds.includes(id)));
      return;
    }
    setSelectedIds((prev) => Array.from(new Set([...prev, ...currentIds])));
  };

  const deleteByIds = async (ids: number[]) => {
    const visibleIds = ids.filter((id) => currentIds.includes(id));
    const hiddenCount = ids.length - visibleIds.length;
    if (visibleIds.length === 0) {
      toast.warning(RU.pickForDelete);
      return;
    }
    if (hiddenCount > 0) toast.info(RU.hiddenSelectedIgnored(hiddenCount));
    if (!window.confirm(RU.confirmDelete(visibleIds.length))) return;
    try {
      await Promise.all(visibleIds.map((id) => deletePaper(id)));
      setSelectedIds((prev) => prev.filter((id) => !visibleIds.includes(id)));
      toast.success(RU.deletedOk(visibleIds.length));
      await fetchData();
    } catch {
      toast.error(RU.deleteError);
    }
  };

  const exportCSV = () => {
    const ids = selectedIds.filter((id) => currentIds.includes(id));
    if (ids.length === 0) {
      toast.warning(RU.pickForExport);
      return;
    }
    const rows = visiblePapers.filter((p) => ids.includes(p.id));
    const csvHeader = [
      "id",
      "title",
      "source",
      "publicationDate",
      "doi",
      "journal",
      "authors",
      "keywords",
      "fullText",
    ];
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
        return row.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(",");
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
            onChange={(e) =>
              setFilters((s) => ({ ...s, query: e.target.value }))
            }
            placeholder={RU.queryPlaceholder}
          />
          <select
            value={filters.source ?? "all"}
            onChange={(e) =>
              setFilters((s) => ({
                ...s,
                source: e.target.value as PaperListFilters["source"],
              }))
            }
          >
            <option value="all">{RU.allSources}</option>
            {PAPER_SOURCES.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={filters.fullTextOnly}
              onChange={(e) =>
                setFilters((s) => ({ ...s, fullTextOnly: e.target.checked }))
              }
            />
            {RU.fullTextOnly}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>{RU.from}</span>
            <input
              type="date"
              value={filters.dateFrom ?? ""}
              onChange={(e) =>
                setFilters((s) => ({ ...s, dateFrom: e.target.value }))
              }
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>{RU.to}</span>
            <input
              type="date"
              value={filters.dateTo ?? ""}
              onChange={(e) =>
                setFilters((s) => ({ ...s, dateTo: e.target.value }))
              }
            />
          </label>
          <select
            value={filters.processingStatus ?? "all"}
            onChange={(e) =>
              setFilters((s) => ({ ...s, processingStatus: e.target.value }))
            }
          >
            <option value="all">{RU.statusAll}</option>
            {statusOptions.map((st) => (
              <option key={st} value={st}>
                {getProcessingStatusLabel(st)}
              </option>
            ))}
          </select>
          {clientDatasetMode && (
            <span className="muted">
              {RU.clientFiltersNote(CLIENT_SCAN_LIMIT, loadedCount, filteredCount)}
            </span>
          )}
        </div>
      </div>

      <div className="panel">
        <h3>{RU.sorting}</h3>
        <div className="filters">
          <select
            value={sort.sortKey}
            onChange={(e) =>
              setSort((s) => ({
                ...s,
                sortKey: e.target.value as SortState["sortKey"],
              }))
            }
          >
            <option value="id">{RU.sortById}</option>
            <option value="authors">{RU.sortByAuthors}</option>
            <option value="createdAt">{RU.sortByCreated}</option>
            <option value="publicationDate">{RU.sortByPublication}</option>
          </select>
          <select
            value={sort.sortDir}
            onChange={(e) =>
              setSort((s) => ({
                ...s,
                sortDir: e.target.value as SortState["sortDir"],
              }))
            }
          >
            <option value="desc">{RU.sortDesc}</option>
            <option value="asc">{RU.sortAsc}</option>
          </select>
        </div>
      </div>

      <div className="actions">
        <button className="btn btn-primary" onClick={exportCSV}>
          {RU.exportCsv}
        </button>
        <button
          className="btn btn-danger"
          onClick={() => deleteByIds(selectedIds)}
          disabled={!currentIds.some((id) => selectedIds.includes(id))}
        >
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
              <input
                type="checkbox"
                checked={allChecked}
                onChange={toggleAllCurrent}
              />
            </th>
            <th>ID</th>
            <th>{RU.colTitle}</th>
            <th>{RU.colAuthors}</th>
            <th>{RU.colSource}</th>
            <th>{RU.colDate}</th>
            <th>DOI</th>
            <th>{RU.colFullText}</th>
            <th>{RU.colStatus}</th>
            <th>{RU.colActions}</th>
          </tr>
        </thead>
        <tbody>
          {visiblePapers.length === 0 ? (
            <tr>
              <td colSpan={10} className="muted">
                {RU.noResults}
              </td>
            </tr>
          ) : (
            visiblePapers.map((p) => {
              const checked = selectedIds.includes(p.id);
              return (
                <tr key={p.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleOne(p.id)}
                    />
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
                  <td>
                    {p.publicationDate
                      ? p.publicationDate.slice(0, 10)
                      : RU.dash}
                  </td>
                  <td>{p.doi ?? RU.dash}</td>
                  <td>{hasFullTextOrPdf(p) ? RU.yes : RU.no}</td>
                  <td>
                    <div className="paper-progress">
                      <div className="paper-progress-head">
                        <span>
                          {getProcessingStatusLabel(p.processingStatus)}
                        </span>
                        <span>
                          {getProcessingProgress(p.processingStatus)}%
                        </span>
                      </div>
                      <div
                        className="paper-progress-track"
                        aria-label={`progress-${p.id}`}
                      >
                        <div
                          className={`paper-progress-fill ${p.processingStatus === "failed" ? "failed" : getProcessingProgress(p.processingStatus) === 100 ? "done" : ""}`}
                          style={{
                            width: `${Math.max(3, getProcessingProgress(p.processingStatus))}%`,
                          }}
                        />
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="actions-inline">
                      <Link className="action-link" to={`/papers/${p.id}`}>
                        {RU.open}
                      </Link>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => deleteByIds([p.id])}
                      >
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

      {totalPages > 1 && (
        <Pagination page={page} totalPages={totalPages} onChange={setPage} />
      )}
    </div>
  );
}
