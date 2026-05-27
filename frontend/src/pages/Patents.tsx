import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  deletePaper,
  exportPapersCsv,
  getPaperProcessingStatuses,
  getPapersPage,
  type PaperListSortBy,
} from "../api/papers";
import Pagination from "../components/ui/Pagination";
import { useToast } from "../components/ui/Toast";
import { useAuthStore } from "../store/authStore";
import {
  getProcessingProgress,
  getProcessingStatusLabel,
  isPaperProcessing,
  PAPER_SOURCES,
} from "../types/paper";
import type { Paper, PaperListFilters } from "../types/paper";

type SortState = {
  sortKey: "id" | "authors" | "createdAt" | "publicationDate";
  sortDir: "asc" | "desc";
};

const PAGE_SIZE = 10;
const DEFAULT_SORT: SortState = { sortKey: "createdAt", sortDir: "desc" };

const RU = {
  pageTitle: "Статьи",
  filters: "Фильтры",
  allSources: "Все источники",
  queryPlaceholder: "Поиск по названию, аннотации, авторам, DOI и ключевым словам",
  fullTextOnly: "Только с извлечённым полным текстом",
  from: "с:",
  to: "по:",
  statusAll: "По статусу: все",
  sorting: "Сортировка",
  sortById: "По ID",
  sortByAuthors: "По авторам",
  sortByCreated: "По дате добавления",
  sortByPublication: "По дате публикации",
  sortDesc: "По убыванию",
  sortAsc: "По возрастанию",
  exportCsv: "Экспорт выбранных на странице",
  exportAllCsv: "Экспорт всех найденных (до 10 000)",
  exporting: "Экспорт...",
  deleteSelected: "Удалить выбранные",
  total: "Найдено",
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
  adminOnly: "Удаление доступно только администратору.",
  confirmDelete: (n: number) => `Удалить ${n} статей из базы?`,
  hiddenSelectedIgnored: (n: number) =>
    `Скрытые выбранные записи не будут удалены: ${n}.`,
  deletedOk: (n: number) => `Удалено ${n} статей`,
  deleteError: "Ошибка при удалении",
  pickForExport: "Выберите элементы на текущей странице для экспорта.",
  exportAllError: "Не удалось экспортировать найденные статьи",
  pickForDelete: "Выберите элементы на текущей странице для удаления.",
} as const;

function hasExtractedFullText(p: Paper) {
  return Boolean(p.hasFullText || (p.fullText && p.fullText.trim().length > 0));
}

function toApiSortKey(sortKey: SortState["sortKey"]): PaperListSortBy {
  if (sortKey === "createdAt") return "created_at";
  if (sortKey === "publicationDate") return "publication_date";
  return sortKey;
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
  "pdf_download_skipped",
  "extracting_pdf_text",
  "pdf_parsed",
  "pdf_text_skipped",
  "fulltext_fallback_parsed",
  "fulltext_unavailable",
  "digitizing_file",
  "formatting_markdown",
  "markdown_ready",
  "markdown_partial",
  "markdown_ready_without_qwen",
  "markdown_failed",
  "markdown_skipped",
  "analyzing_ru",
  "ru_analysis_ready",
  "ru_analysis_fallback",
  "ru_analysis_skipped",
  "extracting_keywords",
  "keywords_ready",
  "keywords_failed",
  "keywords_skipped",
  "qwen_auth_failed",
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

export default function Patents() {
  const toast = useToast();
  const isAdmin = !!useAuthStore((s) => s.user?.is_admin);
  const requestSeq = useRef(0);
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [exportingAll, setExportingAll] = useState(false);
  const debouncedQuery = useDebouncedValue(filters.query ?? "", 450);
  const [statusOptions, setStatusOptions] = useState<{ key: string; label: string }[]>([]);

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

  useEffect(() => {
    getPaperProcessingStatuses()
      .then((items) => {
        const normalized = items
          .filter((item) => item.key)
          .map((item) => ({ key: item.key, label: item.label || getProcessingStatusLabel(item.key) }));
        setStatusOptions(normalized.length ? normalized : PROCESSING_STATUS_OPTIONS.map((key) => ({ key, label: getProcessingStatusLabel(key) })));
      })
      .catch(() => setStatusOptions(PROCESSING_STATUS_OPTIONS.map((key) => ({ key, label: getProcessingStatusLabel(key) }))));
  }, []);

  useEffect(() => {
    setSelectedIds([]);
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

  const fetchData = async (showLoading = true) => {
    const requestId = ++requestSeq.current;
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const response = await getPapersPage({
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        source: filters.source ?? "all",
        query: debouncedQuery,
        fullTextOnly: filters.fullTextOnly,
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
        processingStatus: filters.processingStatus,
        sortBy: toApiSortKey(sort.sortKey),
        sortDir: sort.sortDir,
      });

      if (requestId !== requestSeq.current) return;
      setTotalCount(response.total);
      setPapers(response.papers);
      if (response.total === 0) setSelectedIds([]);
    } catch (e) {
      if (requestId !== requestSeq.current) return;
      setError((e as Error).message);
    } finally {
      if (requestId === requestSeq.current && showLoading) setLoading(false);
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

  const visiblePapers = papers;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

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
    sort.sortKey,
    sort.sortDir,
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
    if (!isAdmin) {
      toast.error(RU.adminOnly);
      return;
    }

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

  const downloadBlobUrl = (url: string, filename: string) => {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportSelectedCSV = () => {
    const ids = selectedIds.filter((id) => currentIds.includes(id));
    if (ids.length === 0) {
      toast.warning(RU.pickForExport);
      return;
    }
    const rows = visiblePapers.filter((p) => ids.includes(p.id));
    const csvHeader = [
      "ID",
      "Название",
      "Источник",
      "Дата публикации",
      "DOI",
      "Журнал",
      "Авторы",
      "Ключевые слова",
      "Извлечённый полный текст",
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
          hasExtractedFullText(p) ? "Да" : "Нет",
        ];
        return row.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(",");
      }),
    ].join("\n");

    const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    downloadBlobUrl(url, "articles_selected_page.csv");
  };

  const exportAllCSV = async () => {
    if (exportingAll) return;
    setExportingAll(true);
    try {
      const url = await exportPapersCsv({
        source: filters.source ?? "all",
        query: debouncedQuery,
        fullTextOnly: filters.fullTextOnly,
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
        processingStatus: filters.processingStatus,
        sortBy: toApiSortKey(sort.sortKey),
        sortDir: sort.sortDir,
        maxRows: 10000,
      });
      downloadBlobUrl(url, "articles_found.csv");
    } catch (e) {
      toast.error(`${RU.exportAllError}: ${(e as Error).message}`);
    } finally {
      setExportingAll(false);
    }
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
            style={{ minWidth: "min(540px, 100%)", flex: "1 1 320px" }}
            value={filters.query ?? ""}
            onChange={(e) =>
              setFilters((s) => ({ ...s, query: e.target.value }))
            }
            placeholder={RU.queryPlaceholder}
            aria-label={RU.queryPlaceholder}
          />
          <select
            value={filters.source ?? "all"}
            onChange={(e) =>
              setFilters((s) => ({
                ...s,
                source: e.target.value as PaperListFilters["source"],
              }))
            }
            aria-label="Фильтр по источнику"
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
            aria-label="Фильтр по статусу обработки"
          >
            <option value="all">{RU.statusAll}</option>
            {statusOptions.map((st) => (
              <option key={st.key} value={st.key}>
                {st.label}
              </option>
            ))}
          </select>
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
            aria-label="Поле сортировки"
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
            aria-label="Направление сортировки"
          >
            <option value="desc">{RU.sortDesc}</option>
            <option value="asc">{RU.sortAsc}</option>
          </select>
        </div>
      </div>

      <div className="actions">
        <button className="btn btn-primary" onClick={exportSelectedCSV}>
          {RU.exportCsv}
        </button>
        <button className="btn" onClick={() => void exportAllCSV()} disabled={exportingAll || totalCount === 0}>
          {exportingAll ? RU.exporting : RU.exportAllCsv}
        </button>
        {isAdmin && (
          <button
            className="btn btn-danger"
            onClick={() => deleteByIds(selectedIds)}
            disabled={!currentIds.some((id) => selectedIds.includes(id))}
          >
            {RU.deleteSelected}
          </button>
        )}
        <div className="counter-badge" style={{ marginLeft: "auto" }}>
          {RU.total}: {totalCount}
        </div>
      </div>

      {loading && <p className="muted">{RU.loading}</p>}
      {error && <p className="error">{error}</p>}

      <div className="table-wrapper">
        <table className="table">
          <caption className="sr-only">Список статей</caption>
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  checked={allChecked}
                  onChange={toggleAllCurrent}
                  aria-label="Выбрать все статьи на текущей странице"
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
                const progress = getProcessingProgress(p.processingStatus);
                return (
                  <tr key={p.id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleOne(p.id)}
                        aria-label={`Выбрать статью ${p.id}`}
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
                    <td>{hasExtractedFullText(p) ? RU.yes : RU.no}</td>
                    <td>
                      <div className="paper-progress">
                        <div className="paper-progress-head">
                          <span>
                            {getProcessingStatusLabel(p.processingStatus)}
                          </span>
                          <span>{progress}%</span>
                        </div>
                        <div
                          className="paper-progress-track"
                          role="progressbar"
                          aria-label={`Прогресс обработки статьи ${p.id}`}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={progress}
                        >
                          <div
                            className={`paper-progress-fill ${p.processingStatus === "failed" ? "failed" : progress === 100 ? "done" : ""}`}
                            style={{
                              width: `${Math.max(3, progress)}%`,
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
                        {isAdmin && (
                          <button
                            type="button"
                            className="btn"
                            onClick={() => deleteByIds([p.id])}
                          >
                            {RU.del}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <Pagination page={page} totalPages={totalPages} onChange={setPage} />
      )}
    </div>
  );
}
