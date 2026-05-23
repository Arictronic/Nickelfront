import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  deletePaper,
  getPaperById,
  getPaperContentParts,
  getPaperPdfUrl,
  regeneratePaperContentPart,
  reprocessPaperContent,
} from "../api/papers";
import { useToast } from "../components/ui/Toast";
import type { Paper, PaperContentPart } from "../types/paper";
import {
  getProcessingProgress,
  getProcessingStatusLabel,
  isPaperProcessing,
} from "../types/paper";

type Tab = "main" | "parts" | "report";
type BusyAction = "delete" | "reprocess" | null;

type DisplayPart = {
  id: number | null;
  title: string;
  pageStart: number | null;
  pageEnd: number | null;
  markdown: string;
  rawText: string | null;
  status: string;
  error: string | null;
  regenerationCount: number;
  rawTextChars: number;
  markdownTextChars: number;
};

const RU = {
  invalidId: "Некорректный ID статьи",
  loading: "Загрузка статьи...",
  notFound: "Статья не найдена.",
  home: "Главная",
  papers: "Статьи",
  authors: "Авторы",
  source: "Источник",
  date: "Дата",
  journal: "Журнал",
  keywords: "Ключевые слова",
  status: "Статус обработки",
  fullText: "Полный текст",
  yes: "Есть",
  no: "Нет",
  open: "Открыть",
  openPdf: "Открыть PDF",
  workerTask: "Worker task",
  tabMain: "Главная",
  tabParts: "Оцифровка по частям",
  tabReport: "Отчет",
  gist: "Суть статьи",
  gistNotReady: "Суть статьи пока не готова.",
  pdfLen: "PDF / markdown (кол. символов",
  articleText: "Текст статьи",
  reportBtn: "Открыть отчет на отдельной странице",
  reprocessBtn: "Перезапустить обработку всего документа",
  parts: "Части документа",
  emptyText: "Текст пуст.",
  selectedPart: "Выбранная часть",
  localMetrics: "Локальные метрики (эвристики)",
  localMetricsHint: "Быстрый локальный разбор выбранной части без обращения к AI.",
  temps: "Температуры (°C)",
  aiAnalysis: "AI анализ (русский)",
  aiNotReady: "Анализ ещё не готов.",
  translation: "Перевод (русский)",
  translationNotReady: "Перевод ещё не готов.",
  processingError: "Ошибка обработки",
  noTextForReport: "Нет текста для отчета.",
  quickOverview: "Части (быстрый обзор)",
  deletePaper: "Удалить статью",
  copyGist: "Копировать суть",
  backToList: "Назад к списку",
  copied: "Скопировано!",
  copyEmpty: "Суть статьи ещё не готова — копировать нечего.",
  deleteOk: "Статья удалена.",
  deleteError: "Не удалось удалить статью",
  reprocessQueued: "Повторная обработка поставлена в очередь.",
  reprocessError: "Не удалось перезапустить обработку",
  regenerateQueued: "Перегенерация части поставлена в очередь.",
  regenerateError: "Не удалось перегенерировать часть",
  regenerate: "Перегенерировать",
  regenerating: "Перегенерация...",
  actionInProgress: "Выполняется...",
  rawText: "Сырой PDF-текст",
  markdownText: "Markdown от Qwen",
  noStoredParts: "Сохранённых частей пока нет. Показываю legacy-разбиение полного текста.",
  confirmDelete: "Удалить статью из базы?",
  unknown: "—",
};

const LEGACY_PAGE_BLOCK_RE = /(?:^|\n)\s*#{1,6}\s*Pages\s+(\d+)\s*-\s*(\d+)\s*\n+/gi;

function normalizeMarkdownForDisplay(text: string): string {
  let value = (text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  if (!value) return "";

  value = value.replace(/^```(?:markdown|md)?\s*/i, "").replace(/\s*```$/i, "").trim();
  value = value.replace(/\\\((.+?)\\\)/gs, (_, body: string) => `$${body.trim()}$`);
  value = value.replace(/\\\[(.+?)\\\]/gs, (_, body: string) => `$$\n${body.trim()}\n$$`);
  value = value.replace(/([^\n])\s+(#{1,6}\s+)/g, "$1\n\n$2");
  value = value.replace(/\n{3,}/g, "\n\n");
  return value;
}

function splitLegacyMarkdownParts(text: string): DisplayPart[] {
  const value = (text || "").trim();
  if (!value) return [];

  const matches = [...value.matchAll(LEGACY_PAGE_BLOCK_RE)];
  if (matches.length) {
    return matches
      .map((match, idx) => {
        const start = (match.index ?? 0) + match[0].length;
        const end = idx + 1 < matches.length ? matches[idx + 1].index ?? value.length : value.length;
        const pageStart = Number(match[1]);
        const pageEnd = Number(match[2]);
        const markdown = value.slice(start, end).trim();
        return {
          id: null,
          title: `Pages ${pageStart}-${pageEnd}`,
          pageStart,
          pageEnd,
          markdown,
          rawText: null,
          status: "legacy",
          error: null,
          regenerationCount: 0,
          rawTextChars: 0,
          markdownTextChars: markdown.length,
        };
      })
      .filter((part) => part.markdown.trim().length > 0);
  }

  const chunkSize = 4500;
  const chunks: DisplayPart[] = [];
  for (let i = 0; i < value.length; i += chunkSize) {
    const markdown = value.slice(i, i + chunkSize).trim();
    if (!markdown) continue;
    chunks.push({
      id: null,
      title: `Часть ${chunks.length + 1}`,
      pageStart: null,
      pageEnd: null,
      markdown,
      rawText: null,
      status: "legacy",
      error: null,
      regenerationCount: 0,
      rawTextChars: 0,
      markdownTextChars: markdown.length,
    });
  }
  return chunks;
}

function mapStoredPart(part: PaperContentPart): DisplayPart {
  const title = `Pages ${part.pageStart}-${part.pageEnd}`;
  return {
    id: part.id,
    title,
    pageStart: part.pageStart,
    pageEnd: part.pageEnd,
    markdown: part.markdownText || part.rawText || "",
    rawText: part.rawText,
    status: part.status,
    error: part.error,
    regenerationCount: part.regenerationCount,
    rawTextChars: part.rawTextChars,
    markdownTextChars: part.markdownTextChars,
  };
}

function approxTokenCount(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function localExtractMetrics(text: string) {
  const lower = text.toLowerCase();
  const keywords = [
    "nickel",
    "superalloy",
    "inconel",
    "hastelloy",
    "creep",
    "tensile",
    "fatigue",
    "yield",
    "temperature",
    "corrosion",
  ];
  const found: Record<string, number> = {};
  for (const k of keywords) {
    const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
    const m = lower.match(re);
    found[k] = m ? m.length : 0;
  }

  const temps = (text.match(/(\d+(?:\.\d+)?)\s*(?:°\s*)?c/gi) ?? []).slice(0, 20);
  const topKeywords = Object.entries(found)
    .sort((a, b) => b[1] - a[1])
    .filter(([, v]) => v > 0)
    .slice(0, 8);

  return { topKeywords, temps };
}

function partStatusLabel(status: string) {
  const value = (status || "").toLowerCase();
  if (value === "ready") return "Готово";
  if (value === "processing") return "Оцифровка файла";
  if (value === "failed") return "Ошибка";
  if (value === "raw_extracted") return "Сырой текст сохранён";
  if (value === "legacy") return "Legacy-текст";
  return status || RU.unknown;
}

function MarkdownText({ text }: { text: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        skipHtml
      >
        {normalizeMarkdownForDisplay(text)}
      </ReactMarkdown>
    </div>
  );
}

export default function PatentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [contentParts, setContentParts] = useState<PaperContentPart[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pollingWarning, setPollingWarning] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("main");
  const [activePartIndex, setActivePartIndex] = useState(0);
  const [showRawText, setShowRawText] = useState(false);
  const [actionBusy, setActionBusy] = useState<BusyAction>(null);
  const [regeneratingPartId, setRegeneratingPartId] = useState<number | null>(null);

  const loadPaper = async (showLoading = true) => {
    const paperId = Number(id);
    if (!paperId || Number.isNaN(paperId)) {
      setLoadError(RU.invalidId);
      setLoading(false);
      return;
    }

    if (showLoading) setLoading(true);
    if (showLoading) setLoadError(null);

    try {
      const nextPaper = await getPaperById(paperId);
      setPaper(nextPaper);
      try {
        const nextParts = await getPaperContentParts(paperId);
        setContentParts(nextParts);
      } catch (partsError) {
        setContentParts([]);
        console.warn("Failed to load paper content parts", partsError);
      }
      setLoadError(null);
      setPollingWarning(null);
    } catch (e) {
      const message = (e as Error).message;
      if (showLoading || !paper) setLoadError(message);
      else setPollingWarning(`Не удалось обновить статус статьи: ${message}`);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    loadPaper();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!paper || !isPaperProcessing(paper.processingStatus)) return;
    const timer = window.setInterval(() => {
      loadPaper(false).catch(() => null);
    }, 4000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paper?.id, paper?.processingStatus]);

  const fullText = paper?.fullText ?? "";
  const hasFullText = Boolean(fullText.trim().length);
  const hasFullTextOrPdf = Boolean(hasFullText || paper?.pdfUrl || paper?.pdfLocalPath);

  const displayParts = useMemo<DisplayPart[]>(() => {
    if (contentParts.length) return contentParts.map(mapStoredPart);
    return splitLegacyMarkdownParts(fullText);
  }, [contentParts, fullText]);

  const selectedPart = displayParts[activePartIndex] ?? null;

  useEffect(() => {
    if (tab === "parts" && !hasFullText && !displayParts.length) setTab("main");
  }, [tab, hasFullText, displayParts.length]);

  useEffect(() => {
    if (activePartIndex >= displayParts.length) setActivePartIndex(0);
  }, [activePartIndex, displayParts.length]);

  const partMetrics = useMemo(() => {
    if (!selectedPart) return null;
    return localExtractMetrics(selectedPart.markdown || selectedPart.rawText || "");
  }, [selectedPart]);

  const onDelete = async () => {
    if (!paper || actionBusy) return;
    if (!window.confirm(RU.confirmDelete)) return;
    setActionBusy("delete");
    setActionError(null);
    try {
      await deletePaper(paper.id);
      toast.success(RU.deleteOk);
      navigate("/papers");
    } catch (e) {
      const message = (e as Error).message;
      setActionError(`${RU.deleteError}: ${message}`);
      toast.error(`${RU.deleteError}: ${message}`);
    } finally {
      setActionBusy(null);
    }
  };

  const onReprocess = async () => {
    if (!paper || actionBusy) return;
    setActionBusy("reprocess");
    setActionError(null);
    try {
      await reprocessPaperContent(paper.id);
      toast.success(RU.reprocessQueued);
      await loadPaper(false);
    } catch (e) {
      const message = (e as Error).message;
      setActionError(`${RU.reprocessError}: ${message}`);
      toast.error(`${RU.reprocessError}: ${message}`);
    } finally {
      setActionBusy(null);
    }
  };

  const onRegeneratePart = async (part: DisplayPart) => {
    if (!paper || !part.id || regeneratingPartId) return;
    setRegeneratingPartId(part.id);
    setActionError(null);
    try {
      await regeneratePaperContentPart(paper.id, part.id);
      toast.success(RU.regenerateQueued);
      await loadPaper(false);
    } catch (e) {
      const message = (e as Error).message;
      setActionError(`${RU.regenerateError}: ${message}`);
      toast.error(`${RU.regenerateError}: ${message}`);
    } finally {
      setRegeneratingPartId(null);
    }
  };

  const copyGist = async () => {
    if (!paper?.summaryRu?.trim()) {
      toast.warning(RU.copyEmpty);
      return;
    }
    try {
      await navigator.clipboard.writeText(paper.summaryRu);
      toast.success(RU.copied);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  if (loading) return <p className="muted">{RU.loading}</p>;
  if (loadError && !paper) return <p className="error">{loadError}</p>;
  if (!paper) return <p className="muted">{RU.notFound}</p>;

  return (
    <div className="page">
      <p className="muted">
        <Link to="/dashboard">{RU.home}</Link> → <Link to="/papers">{RU.papers}</Link> → {paper.title}
      </p>

      {actionError && <p className="error">{actionError}</p>}
      {pollingWarning && <p className="muted">{pollingWarning}</p>}

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>{paper.title}</h2>
        <div className="detail-grid">
          <p><strong>{RU.authors}:</strong> {paper.authors.length ? paper.authors.slice(0, 4).join(", ") + (paper.authors.length > 4 ? "..." : "") : RU.unknown}</p>
          <p><strong>{RU.source}:</strong> {paper.source}</p>
          <p><strong>{RU.date}:</strong> {paper.publicationDate ? paper.publicationDate.slice(0, 10) : RU.unknown}</p>
          <p><strong>{RU.journal}:</strong> {paper.journal ?? RU.unknown}</p>
          <p><strong>DOI:</strong> {paper.doi ?? RU.unknown}</p>
          <p><strong>{RU.keywords}:</strong> {paper.keywords.length ? paper.keywords.slice(0, 10).join(", ") : RU.unknown}</p>
          <div className="detail-progress">
            <div className="paper-progress-head">
              <strong>{RU.status}:</strong>
              <span>{getProcessingStatusLabel(paper.processingStatus)} - {getProcessingProgress(paper.processingStatus)}%</span>
            </div>
            <div className="paper-progress-track" aria-label={`paper-${paper.id}-progress`}>
              <div
                className={`paper-progress-fill ${paper.processingStatus === "failed" ? "failed" : getProcessingProgress(paper.processingStatus) === 100 ? "done" : ""}`}
                style={{ width: `${Math.max(3, getProcessingProgress(paper.processingStatus))}%` }}
              />
            </div>
          </div>
          <p><strong>{RU.fullText}:</strong> {hasFullTextOrPdf ? RU.yes : RU.no}</p>
          <p><strong>URL:</strong> {paper.url ? <a href={paper.url} target="_blank" rel="noreferrer" className="action-link">{RU.open}</a> : RU.unknown}</p>
          <p><strong>PDF:</strong> {paper.pdfUrl || paper.pdfLocalPath ? <a href={getPaperPdfUrl(paper.id)} target="_blank" rel="noreferrer" className="action-link">{RU.openPdf}</a> : RU.unknown}</p>
          <p><strong>{RU.workerTask}:</strong> {paper.contentTaskId ?? RU.unknown}</p>
        </div>
      </div>

      <div className="tabs">
        <button className={`btn ${tab === "main" ? "btn-primary" : ""}`} onClick={() => setTab("main")}>{RU.tabMain}</button>
        {(hasFullText || displayParts.length > 0) && (
          <button className={`btn ${tab === "parts" ? "btn-primary" : ""}`} onClick={() => setTab("parts")}>{RU.tabParts}</button>
        )}
        <button className={`btn ${tab === "report" ? "btn-primary" : ""}`} onClick={() => setTab("report")}>{RU.tabReport}</button>
      </div>

      {tab === "main" && (
        <article className="panel">
          {paper.summaryRu ? (
            <>
              <h3 style={{ marginTop: 0 }}>{RU.gist}</h3>
              <p style={{ whiteSpace: "pre-wrap" }}>{paper.summaryRu}</p>
            </>
          ) : <p className="muted">{RU.gistNotReady}</p>}

          {(paper.pdfUrl || paper.pdfLocalPath) && (
            <>
              <h3 style={{ marginTop: 18 }}>{RU.pdfLen}: {paper.fullText?.length ?? 0})</h3>
              <iframe
                title="paper-pdf"
                src={getPaperPdfUrl(paper.id)}
                style={{ width: "100%", height: 640, border: "1px solid #e5e7eb", borderRadius: 8 }}
              />
              {paper.fullText && (
                <>
                  <h3 style={{ marginTop: 18 }}>{RU.articleText}</h3>
                  {displayParts.length ? (
                    <div className="markdown-parts-readable">
                      {displayParts.map((part, idx) => (
                        <section className="markdown-part-readonly" key={`${part.id ?? "legacy"}-${idx}`}>
                          <div className="markdown-part-header compact">
                            <h4>{part.title}</h4>
                            <span className="muted">{partStatusLabel(part.status)}</span>
                          </div>
                          <MarkdownText text={part.markdown} />
                        </section>
                      ))}
                    </div>
                  ) : (
                    <MarkdownText text={paper.fullText} />
                  )}
                </>
              )}
            </>
          )}

          <div style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => navigate(`/papers/${paper.id}/report`)}>{RU.reportBtn}</button>
            <button className="btn" style={{ marginLeft: 10 }} onClick={onReprocess} disabled={actionBusy === "reprocess"}>
              {actionBusy === "reprocess" ? RU.actionInProgress : RU.reprocessBtn}
            </button>
          </div>
        </article>
      )}

      {tab === "parts" && (
        <article className="panel">
          {!contentParts.length && displayParts.length > 0 && <p className="muted">{RU.noStoredParts}</p>}
          <div className="markdown-parts-layout">
            <div className="panel markdown-parts-sidebar">
              <h3 style={{ marginTop: 0 }}>{RU.parts}</h3>
              {!displayParts.length ? <p className="muted">{RU.emptyText}</p> : (
                <div className="markdown-parts-list">
                  {displayParts.map((part, idx) => (
                    <button
                      key={`${part.id ?? "legacy"}-${idx}`}
                      className={`btn markdown-part-nav ${idx === activePartIndex ? "btn-primary" : ""}`}
                      onClick={() => setActivePartIndex(idx)}
                    >
                      <span>{part.title}</span>
                      <small>{partStatusLabel(part.status)}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="panel markdown-part-card">
              {selectedPart ? (
                <>
                  <div className="markdown-part-header">
                    <div>
                      <h3 style={{ margin: 0 }}>{selectedPart.title}</h3>
                      <p className="muted" style={{ margin: "6px 0 0" }}>
                        {partStatusLabel(selectedPart.status)} · raw {selectedPart.rawTextChars || selectedPart.rawText?.length || 0} chars · markdown {selectedPart.markdownTextChars || selectedPart.markdown.length} chars
                        {selectedPart.regenerationCount ? ` · регенераций: ${selectedPart.regenerationCount}` : ""}
                      </p>
                    </div>
                    <div className="markdown-part-actions">
                      {selectedPart.rawText && (
                        <button className="btn" onClick={() => setShowRawText((value) => !value)}>
                          {showRawText ? RU.markdownText : RU.rawText}
                        </button>
                      )}
                      <button
                        className="btn btn-primary"
                        disabled={!selectedPart.id || regeneratingPartId === selectedPart.id}
                        onClick={() => onRegeneratePart(selectedPart)}
                        title={!selectedPart.id ? "Перегенерация доступна только для сохранённых частей" : undefined}
                      >
                        {regeneratingPartId === selectedPart.id ? RU.regenerating : RU.regenerate}
                      </button>
                    </div>
                  </div>

                  {selectedPart.error && <p className="error">{selectedPart.error}</p>}

                  {showRawText && selectedPart.rawText ? (
                    <pre className="raw-text-box">{selectedPart.rawText}</pre>
                  ) : (
                    <MarkdownText text={selectedPart.markdown} />
                  )}

                  <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "14px 0" }} />
                  <h3 style={{ marginTop: 0 }}>{RU.localMetrics}</h3>
                  <p className="muted">{RU.localMetricsHint}</p>
                  {partMetrics && (
                    <div className="detail-grid" style={{ marginTop: 10 }}>
                      <p><strong>Top keywords:</strong> {partMetrics.topKeywords.length ? partMetrics.topKeywords.map(([k, v]) => `${k}=${v}`).join(", ") : RU.unknown}</p>
                      <p><strong>{RU.temps}:</strong> {partMetrics.temps.length ? partMetrics.temps.join(", ") : RU.unknown}</p>
                    </div>
                  )}
                </>
              ) : <p className="muted">{RU.emptyText}</p>}
            </div>
          </div>
        </article>
      )}

      {tab === "report" && (
        <article className="panel">
          <h3>{RU.aiAnalysis}</h3>
          {paper.analysisRu ? <p style={{ whiteSpace: "pre-wrap" }}>{paper.analysisRu}</p> : <p className="muted">{RU.aiNotReady}</p>}

          <h3 style={{ marginTop: 18 }}>{RU.translation}</h3>
          {paper.translationRu ? <p style={{ whiteSpace: "pre-wrap" }}>{paper.translationRu}</p> : <p className="muted">{RU.translationNotReady}</p>}

          {paper.processingError && <p className="error" style={{ marginTop: 12 }}>{RU.processingError}: {paper.processingError}</p>}

          {!displayParts.length ? <p className="muted">{RU.noTextForReport}</p> : (
            <>
              <h3>{RU.quickOverview}</h3>
              <div className="markdown-parts-overview">
                {displayParts.slice(0, 8).map((part, idx) => {
                  const m = localExtractMetrics(part.markdown);
                  return (
                    <article className="panel" key={`${part.id ?? "legacy"}-${idx}`} style={{ boxShadow: "none", padding: 12 }}>
                      <p className="muted">{part.title}</p>
                      <p style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 13 }}>
                        {(m.topKeywords.length ? m.topKeywords.map(([k, v]) => `${k}:${v}`).join(", ") : "метрики не найдены") + "\n\n"}
                        {part.markdown.slice(0, 300)}...
                      </p>
                    </article>
                  );
                })}
              </div>
              {displayParts.length > 8 && <p className="muted">Показаны первые 8 частей.</p>}
            </>
          )}
        </article>
      )}

      <div className="actions">
        <button className="btn btn-danger" onClick={onDelete} disabled={actionBusy === "delete"}>
          {actionBusy === "delete" ? RU.actionInProgress : RU.deletePaper}
        </button>
        <button className="btn" onClick={() => void copyGist()}>{RU.copyGist}</button>
        <button className="btn" onClick={() => navigate("/papers")}>{RU.backToList}</button>
      </div>
    </div>
  );
}
