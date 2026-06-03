import { useEffect, useMemo, useRef, useState } from "react";
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
  getProcessingStatusKey,
  getProcessingStatusLabel,
  isPaperProcessing,
  PAPER_SOURCES,
} from "../types/paper";
import type { Paper, PaperListFilters, PaperProcessingStatusInfo } from "../types/paper";

type SortState = {
  sortKey: "id" | "authors" | "createdAt" | "publicationDate" | "relevance";
  sortDir: "asc" | "desc";
};

type StatusTone = "pending" | "processing" | "success" | "warning" | "error" | "unknown";

const DEFAULT_PAGE_SIZE = 25;
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
const DEFAULT_SORT: SortState = { sortKey: "createdAt", sortDir: "desc" };
const DEFAULT_FILTERS: PaperListFilters = {
  source: "all",
  fullTextOnly: false,
  dateFrom: "",
  dateTo: "",
  query: "",
  processingStatus: "all",
  translationStatus: "all",
};

const RU = {
  pageTitle: "Статьи",
  filters: "Фильтры и сортировка",
  allSources: "Все источники",
  queryPlaceholder: "Поиск по названию, аннотации, авторам, DOI и ключевым словам",
  searchLabel: "Поиск",
  sourceLabel: "Источник",
  statusLabel: "Статус обработки",
  translationStatusLabel: "Статус перевода",
  fullTextOnly: "Только с извлечённым полным текстом",
  dateFromLabel: "Дата с",
  dateToLabel: "Дата по",
  statusAll: "Все статусы",
  sorting: "Сортировка",
  sortById: "По ID",
  sortByAuthors: "По авторам",
  sortByCreated: "По дате добавления",
  sortByPublication: "По дате публикации",
  sortByRelevance: "По релевантности",
  sortDesc: "По убыванию",
  sortAsc: "По возрастанию",
  pageSize: "На странице",
  find: "Найти",
  searching: "Поиск...",
  resetFilters: "Сбросить фильтры",
  activeFilters: "Активных фильтров",
  exportCsv: "Экспорт выбранных на странице",
  exportAllCsv: "Экспорт всех найденных (до 10 000)",
  exporting: "Экспорт...",
  refresh: "Обновить",
  refreshing: "Обновление...",
  deleteSelected: "Удалить выбранные",
  total: "Найдено",
  selected: "Выбрано",
  loading: "Загрузка...",
  noResults: "Нет результатов.",
  colTitle: "Название",
  colAuthors: "Авторы",
  colSource: "Источник",
  colLanguage: "Язык",
  colDate: "Дата",
  colStatus: "Статус",
  translationStatusEmpty: "Перевод не запускался",
  colFullText: "Полный текст",
  colActions: "Действия",
  fullTextYes: "Есть текст",
  fullTextNo: "Нет текста",
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

const STATUS_GROUP_LABELS: Record<StatusTone, string> = {
  pending: "Ожидает",
  processing: "В работе",
  success: "Готово",
  warning: "Готово с предупреждением",
  error: "Ошибка",
  unknown: "Прочее",
};

const STATUS_GROUP_ORDER: StatusTone[] = ["pending", "processing", "warning", "error", "success", "unknown"];

const TRANSLATION_STATUS_OPTIONS: PaperProcessingStatusInfo[] = [
  { key: "translating_article", label: "Перевод текста статьи", group: "processing", final: false },
  { key: "translation_ready", label: "Перевод текста готов", group: "success", final: true },
  { key: "translation_partial", label: "Перевод текста частично готов", group: "warning", final: true },
  { key: "translation_failed", label: "Ошибка перевода текста", group: "error", final: true },
];

const TRANSLATION_STATUS_KEYS = new Set(TRANSLATION_STATUS_OPTIONS.map((item) => item.key));

const WARNING_STATUS_KEYS = new Set([
  "fulltext_fallback_parsed",
  "fulltext_unavailable",
  "markdown_partial",
  "markdown_ready_without_qwen",
  "markdown_skipped",
  "pdf_download_skipped",
  "pdf_text_skipped",
  "pdf_unavailable",
  "ready_with_fallback",
  "ru_analysis_fallback",
  "ru_analysis_skipped",
  "keywords_skipped",
  "embedding_skipped",
]);

const ERROR_STATUS_KEYS = new Set([
  "failed",
  "content_queue_failed",
  "embedding_failed",
  "pdf_text_failed",
  "ru_analysis_failed",
  "keywords_failed",
  "markdown_failed",
  "pdf_download_failed",
  "qwen_auth_failed",
]);

const SUCCESS_STATUS_KEYS = new Set([
  "completed",
  "page_regenerated",
  "ready",
]);

const PENDING_STATUS_KEYS = new Set([
  "pending",
  "queued_for_content_processing",
]);

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
  "page_regenerated",
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
  "embedding_skipped",
  "ready",
  "ready_with_fallback",
  "completed",
  "failed",
];

const PROCESSING_STATUS_FILTER_OPTIONS = PROCESSING_STATUS_OPTIONS.filter(
  (key) => !TRANSLATION_STATUS_KEYS.has(key),
);

function hasExtractedFullText(p: Paper) {
  return Boolean(p.hasFullText || (p.fullText && p.fullText.trim().length > 0));
}

function formatPaperLanguage(p: Paper) {
  const name = (p.languageName || "").trim();
  const code = (p.languageCode || "").trim();
  const normalizedOriginal = code.toLowerCase();
  const base = name && name !== "Не определён" ? name : code && code !== "unknown" ? code : RU.dash;
  const translatedCodes = Array.from(new Set((p.availableLanguageCodes ?? [])
    .map((item) => String(item || "").trim().toLowerCase())
    .filter((item) => item && item !== normalizedOriginal)));
  const suffix = translatedCodes.length ? ` · ${translatedCodes.map((item) => item.toUpperCase()).join(" · ")}` : "";
  if (base === RU.dash) return suffix ? translatedCodes.map((item) => item.toUpperCase()).join(" · ") : base;
  if (typeof p.languageConfidence === "number" && Number.isFinite(p.languageConfidence)) {
    const percent = Math.round(Math.max(0, Math.min(1, p.languageConfidence)) * 100);
    return `${base} · ${percent}%${suffix}`;
  }
  return `${base}${suffix}`;
}

function getTranslationStatusLabel(status: string | null | undefined): string {
  const key = getProcessingStatusKey(status);
  if (!key) return RU.translationStatusEmpty;
  const known = TRANSLATION_STATUS_OPTIONS.find((item) => item.key === key);
  return known?.label || getProcessingStatusLabel(status);
}

function getTranslationStatusTone(status: string | null | undefined): StatusTone {
  const key = getProcessingStatusKey(status);
  if (!key) return "unknown";
  const known = TRANSLATION_STATUS_OPTIONS.find((item) => item.key === key);
  if (known) return known.group as StatusTone;
  return resolveStatusTone(key, null);
}

function isTranslationProcessing(status: string | null | undefined): boolean {
  return getProcessingStatusKey(status) === "translating_article";
}

function formatAuthors(authors: string[]) {
  if (!authors.length) return RU.dash;
  const visible = authors.slice(0, 2).join(", ");
  return authors.length > 2 ? `${visible}…` : visible;
}

function toApiSortKey(sortKey: SortState["sortKey"]): PaperListSortBy {
  if (sortKey === "createdAt") return "created_at";
  if (sortKey === "publicationDate") return "publication_date";
  return sortKey;
}

function resolveStatusTone(key: string, info: PaperProcessingStatusInfo | null): StatusTone {
  const normalized = getProcessingStatusKey(key) || key;
  if (ERROR_STATUS_KEYS.has(normalized)) return "error";
  if (WARNING_STATUS_KEYS.has(normalized)) return "warning";
  if (SUCCESS_STATUS_KEYS.has(normalized)) return "success";
  if (PENDING_STATUS_KEYS.has(normalized)) return "pending";

  const group = (info?.group || "unknown") as StatusTone;
  if (group === "error" || group === "warning" || group === "success" || group === "pending") return group;
  if (group === "processing") return "processing";
  if (isPaperProcessing(normalized)) return "processing";
  return "unknown";
}

function fallbackStatusInfo(key: string): PaperProcessingStatusInfo {
  const tone = resolveStatusTone(key, null);
  return {
    key,
    label: getProcessingStatusLabel(key),
    group: tone,
    final: !isPaperProcessing(key),
  };
}

function statusProgressClass(info: PaperProcessingStatusInfo | null, statusKey: string, progress: number) {
  const tone = resolveStatusTone(statusKey, info);
  if (tone === "error") return "failed";
  if (tone === "warning") return "warning";
  if (tone === "success" || progress >= 100) return "done";
  if (tone === "pending") return "pending";
  return "";
}

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
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [filters, setFilters] = useState<PaperListFilters>(DEFAULT_FILTERS);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [exportingAll, setExportingAll] = useState(false);
  const debouncedQuery = useDebouncedValue(filters.query ?? "", 450);
  const [statusOptions, setStatusOptions] = useState<PaperProcessingStatusInfo[]>([]);

  useEffect(() => {
    setPage(1);
  }, [
    filters.source,
    debouncedQuery,
    filters.fullTextOnly,
    filters.dateFrom,
    filters.dateTo,
    filters.processingStatus,
    filters.translationStatus,
    sort.sortKey,
    sort.sortDir,
    pageSize,
  ]);

  useEffect(() => {
    getPaperProcessingStatuses()
      .then((items) => {
        const normalized = items
          .filter((item) => item.key && !TRANSLATION_STATUS_KEYS.has(item.key))
          .map((item) => ({
            ...item,
            label: item.label || getProcessingStatusLabel(item.key),
            group: resolveStatusTone(item.key, item),
            final: Boolean(item.final),
          }));
        setStatusOptions(normalized.length ? normalized : PROCESSING_STATUS_FILTER_OPTIONS.map(fallbackStatusInfo));
      })
      .catch(() => setStatusOptions(PROCESSING_STATUS_FILTER_OPTIONS.map(fallbackStatusInfo)));
  }, []);

  useEffect(() => {
    if (!debouncedQuery.trim() && sort.sortKey === "relevance") {
      setSort(DEFAULT_SORT);
    }
  }, [debouncedQuery, sort.sortKey]);

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
    filters.translationStatus,
    sort.sortKey,
    sort.sortDir,
    pageSize,
  ]);

  const fetchData = async (showLoading = true, queryOverride?: string, pageOverride?: number) => {
    const requestId = ++requestSeq.current;
    const requestedPage = pageOverride ?? page;
    const requestedQuery = queryOverride ?? debouncedQuery;
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const response = await getPapersPage({
        limit: pageSize,
        offset: (requestedPage - 1) * pageSize,
        source: filters.source ?? "all",
        query: requestedQuery,
        fullTextOnly: filters.fullTextOnly,
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
        processingStatus: filters.processingStatus,
        translationStatus: filters.translationStatus,
        sortBy: toApiSortKey(sort.sortKey),
        sortDir: sort.sortDir,
      });

      if (requestId !== requestSeq.current) return;
      const nextTotalPages = Math.max(1, Math.ceil((response.total ?? 0) / pageSize));
      if (requestedPage > nextTotalPages) {
        setTotalCount(response.total);
        setPapers([]);
        setPage(nextTotalPages);
        return;
      }
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
    pageSize,
    filters.source,
    debouncedQuery,
    filters.fullTextOnly,
    filters.dateFrom,
    filters.dateTo,
    filters.processingStatus,
    filters.translationStatus,
    sort.sortKey,
    sort.sortDir,
  ]);

  const visiblePapers = papers;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const statusInfoByKey = useMemo(() => new Map(statusOptions.map((item) => [item.key, item])), [statusOptions]);
  const groupedStatusOptions = useMemo(() => {
    return STATUS_GROUP_ORDER.map((group) => ({
      group,
      items: statusOptions.filter((item) => resolveStatusTone(item.key, item) === group),
    })).filter((group) => group.items.length > 0);
  }, [statusOptions]);

  const currentIds = visiblePapers.map((p) => p.id);
  const selectedOnPage = currentIds.filter((id) => selectedIds.includes(id)).length;
  const allChecked = currentIds.length > 0 && currentIds.every((id) => selectedIds.includes(id));
  const hasProcessingPapers = visiblePapers.some((p) => {
    const statusKey = getProcessingStatusKey(p.processingStatus);
    const info = statusInfoByKey.get(statusKey);
    return (info ? !info.final : isPaperProcessing(p.processingStatus)) || isTranslationProcessing(p.translationStatus);
  });
  const activeFiltersCount = [
    Boolean((filters.query ?? "").trim()),
    filters.source && filters.source !== "all",
    filters.fullTextOnly,
    Boolean(filters.dateFrom),
    Boolean(filters.dateTo),
    filters.processingStatus && filters.processingStatus !== "all",
    filters.translationStatus && filters.translationStatus !== "all",
  ].filter(Boolean).length;

  useEffect(() => {
    if (!hasProcessingPapers) return;
    const timer = window.setInterval(() => {
      fetchData(false).catch(() => null);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [
    hasProcessingPapers,
    page,
    pageSize,
    filters.source,
    debouncedQuery,
    filters.fullTextOnly,
    filters.dateFrom,
    filters.dateTo,
    filters.processingStatus,
    filters.translationStatus,
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

  const applyFilters = () => {
    setPage(1);
    fetchData(true, (filters.query ?? "").trim(), 1).catch(() => null);
  };

  const resetFilters = () => {
    setFilters({ ...DEFAULT_FILTERS });
    setSort(DEFAULT_SORT);
    setPage(1);
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
      "Язык",
      "Дата публикации",
      "DOI",
      "Журнал",
      "Авторы",
      "Ключевые слова",
      "Извлечённый полный текст",
      "Статус",
      "Статус перевода",
    ];
    const csv = [
      csvHeader.join(","),
      ...rows.map((p) => {
        const row = [
          p.id,
          p.title,
          p.source,
          formatPaperLanguage(p) === RU.dash ? "" : formatPaperLanguage(p),
          p.publicationDate ?? "",
          p.doi ?? "",
          p.journal ?? "",
          (p.authors ?? []).join("; "),
          (p.keywords ?? []).join("; "),
          hasExtractedFullText(p) ? "Да" : "Нет",
          getProcessingStatusLabel(p.processingStatus),
          getTranslationStatusLabel(p.translationStatus),
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
        translationStatus: filters.translationStatus,
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
    <div className="page papers-page">
      <div className="page-head papers-page-head">
        <div>
          <h2>{RU.pageTitle}</h2>
          <p className="page-subtitle">
            Единый список статей и патентных записей с фильтрами, прогрессом обработки и экспортом.
          </p>
        </div>
      </div>

      <div className="panel papers-toolbar-panel">
        <div className="papers-toolbar-title-row">
          <h3>{RU.filters}</h3>
          <span className="counter-badge">{RU.activeFilters}: {activeFiltersCount}</span>
        </div>
        <div className="papers-filter-grid">
          <label className="papers-filter-field papers-filter-search">
            <span>{RU.searchLabel}</span>
            <input
              className="input"
              value={filters.query ?? ""}
              onChange={(e) => setFilters((s) => ({ ...s, query: e.target.value }))}
              placeholder={RU.queryPlaceholder}
              aria-label={RU.queryPlaceholder}
            />
          </label>

          <label className="papers-filter-field">
            <span>{RU.sourceLabel}</span>
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
          </label>

          <label className="papers-filter-field">
            <span>{RU.statusLabel}</span>
            <select
              value={filters.processingStatus ?? "all"}
              onChange={(e) => setFilters((s) => ({ ...s, processingStatus: e.target.value }))}
              aria-label="Фильтр по статусу обработки"
            >
              <option value="all">{RU.statusAll}</option>
              {groupedStatusOptions.map(({ group, items }) => (
                <optgroup key={group} label={STATUS_GROUP_LABELS[group]}>
                  {items.map((st) => (
                    <option key={st.key} value={st.key}>
                      {st.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>

          <label className="papers-filter-field">
            <span>{RU.translationStatusLabel}</span>
            <select
              value={filters.translationStatus ?? "all"}
              onChange={(e) => setFilters((s) => ({ ...s, translationStatus: e.target.value }))}
              aria-label="Фильтр по статусу перевода"
            >
              <option value="all">{RU.statusAll}</option>
              {TRANSLATION_STATUS_OPTIONS.map((st) => (
                <option key={st.key} value={st.key}>
                  {st.label}
                </option>
              ))}
            </select>
          </label>

          <label className="papers-filter-field papers-filter-check">
            <input
              type="checkbox"
              checked={filters.fullTextOnly}
              onChange={(e) => setFilters((s) => ({ ...s, fullTextOnly: e.target.checked }))}
            />
            <span>{RU.fullTextOnly}</span>
          </label>

          <label className="papers-filter-field">
            <span>{RU.dateFromLabel}</span>
            <input
              type="date"
              value={filters.dateFrom ?? ""}
              onChange={(e) => setFilters((s) => ({ ...s, dateFrom: e.target.value }))}
            />
          </label>

          <label className="papers-filter-field">
            <span>{RU.dateToLabel}</span>
            <input
              type="date"
              value={filters.dateTo ?? ""}
              onChange={(e) => setFilters((s) => ({ ...s, dateTo: e.target.value }))}
            />
          </label>

          <label className="papers-filter-field">
            <span>{RU.sorting}</span>
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
              <option value="relevance" disabled={!debouncedQuery.trim()}>{RU.sortByRelevance}</option>
            </select>
          </label>

          <label className="papers-filter-field">
            <span>Направление</span>
            <select
              value={sort.sortDir}
              onChange={(e) =>
                setSort((s) => ({
                  ...s,
                  sortDir: e.target.value as SortState["sortDir"],
                }))
              }
              aria-label="Направление сортировки"
              disabled={sort.sortKey === "relevance"}
            >
              <option value="desc">{RU.sortDesc}</option>
              <option value="asc">{RU.sortAsc}</option>
            </select>
          </label>

          <label className="papers-filter-field">
            <span>{RU.pageSize}</span>
            <select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              aria-label="Количество записей на странице"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
          </label>

        </div>
        <div className="papers-filter-actions-row">
          <button
            className="btn btn-primary papers-filter-action-button"
            type="button"
            onClick={applyFilters}
            disabled={loading}
          >
            {loading ? RU.searching : RU.find}
          </button>
          <button className="btn btn-ghost papers-filter-action-button" type="button" onClick={resetFilters}>
            {RU.resetFilters}
          </button>
        </div>
      </div>

      <div className="actions papers-actions">
        <button className="btn" onClick={() => void fetchData()} disabled={loading}>
          {loading ? RU.refreshing : RU.refresh}
        </button>
        <button className="btn btn-primary" onClick={exportSelectedCSV} disabled={selectedOnPage === 0}>
          {RU.exportCsv}
        </button>
        <button className="btn" onClick={() => void exportAllCSV()} disabled={exportingAll || totalCount === 0}>
          {exportingAll ? RU.exporting : RU.exportAllCsv}
        </button>
        {isAdmin && (
          <button
            className="btn btn-danger"
            onClick={() => deleteByIds(selectedIds)}
            disabled={selectedOnPage === 0}
          >
            {RU.deleteSelected}
          </button>
        )}
        <div className="papers-actions-spacer" />
        <div className="counter-badge">{RU.selected}: {selectedOnPage}</div>
        <div className="counter-badge">{RU.total}: {totalCount}</div>
      </div>

      {loading && <p className="muted">{RU.loading}</p>}
      {error && <p className="error">{error}</p>}

      <div className="table-wrapper papers-table-wrapper">
        <table className="table papers-table">
          <caption className="sr-only">Список статей</caption>
          <colgroup>
            <col className="papers-col-check" />
            <col className="papers-col-id" />
            <col className="papers-col-title" />
            <col className="papers-col-authors" />
            <col className="papers-col-source" />
            <col className="papers-col-language" />
            <col className="papers-col-date" />
            <col className="papers-col-fulltext" />
            <col className="papers-col-status" />
            <col className="papers-col-actions" />
          </colgroup>
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
              <th>{RU.colLanguage}</th>
              <th>{RU.colDate}</th>
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
                const statusKey = getProcessingStatusKey(p.processingStatus);
                const statusInfo = statusInfoByKey.get(statusKey) ?? fallbackStatusInfo(statusKey);
                const statusTone = resolveStatusTone(statusKey, statusInfo);
                const progress = statusInfo?.final ? 100 : getProcessingProgress(p.processingStatus);
                const statusLabel = p.processingStatus?.startsWith("digitizing_file:")
                  ? getProcessingStatusLabel(p.processingStatus)
                  : statusInfo?.label || getProcessingStatusLabel(p.processingStatus);
                const progressClass = statusProgressClass(statusInfo, statusKey, progress);
                const fullText = hasExtractedFullText(p);
                const authorsTitle = p.authors.length ? p.authors.join(", ") : RU.dash;
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
                    <td className="paper-id-cell">{p.id}</td>
                    <td className="paper-title-cell">
                      <Link className="paper-title-link" to={`/papers/${p.id}`} title={p.title}>
                        {p.title}
                      </Link>
                    </td>
                    <td className="paper-authors-cell" title={authorsTitle}>
                      {formatAuthors(p.authors)}
                    </td>
                    <td><span className="paper-source-badge">{p.source}</span></td>
                    <td className="paper-muted-cell">{formatPaperLanguage(p)}</td>
                    <td className="paper-muted-cell">
                      {p.publicationDate ? p.publicationDate.slice(0, 10) : RU.dash}
                    </td>
                    <td>
                      <span className={`status-pill ${fullText ? "success" : "neutral"}`}>
                        {fullText ? RU.fullTextYes : RU.fullTextNo}
                      </span>
                    </td>
                    <td>
                      <div className={`paper-progress paper-progress-${statusTone}`}>
                        <div className="paper-progress-head">
                          <span>{statusLabel}</span>
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
                            className={`paper-progress-fill ${progressClass}`}
                            style={{ width: `${Math.max(3, progress)}%` }}
                          />
                        </div>
                      </div>
                      {p.translationStatus && (
                        <div className={`paper-translation-status paper-translation-status-${getTranslationStatusTone(p.translationStatus)}`}>
                          {getTranslationStatusLabel(p.translationStatus)}
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="actions-inline papers-row-actions">
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
