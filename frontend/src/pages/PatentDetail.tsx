import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { deletePaper, getPaperById, getPaperPdfUrl, reprocessPaperContent } from "../api/papers";
import type { Paper } from "../types/paper";
import { getProcessingStatusLabel } from "../types/paper";

type Tab = "main" | "parts" | "report";

const RU = {
  invalidId: "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 ID \u0441\u0442\u0430\u0442\u044c\u0438",
  loading: "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u0441\u0442\u0430\u0442\u044c\u0438...",
  notFound: "\u0421\u0442\u0430\u0442\u044c\u044f \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430.",
  home: "\u0413\u043b\u0430\u0432\u043d\u0430\u044f",
  papers: "\u0421\u0442\u0430\u0442\u044c\u0438",
  authors: "\u0410\u0432\u0442\u043e\u0440\u044b",
  source: "\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a",
  date: "\u0414\u0430\u0442\u0430",
  journal: "\u0416\u0443\u0440\u043d\u0430\u043b",
  keywords: "\u041a\u043b\u044e\u0447\u0435\u0432\u044b\u0435 \u0441\u043b\u043e\u0432\u0430",
  status: "\u0421\u0442\u0430\u0442\u0443\u0441 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438",
  fullText: "full_text",
  yes: "\u0415\u0441\u0442\u044c",
  no: "\u041d\u0435\u0442",
  open: "\u041e\u0442\u043a\u0440\u044b\u0442\u044c",
  openPdf: "\u041e\u0442\u043a\u0440\u044b\u0442\u044c PDF",
  workerTask: "Worker task",
  tabMain: "\u0413\u043b\u0430\u0432\u043d\u0430\u044f",
  tabParts: "\u0427\u0430\u0441\u0442\u0438 \u0442\u0435\u043a\u0441\u0442\u0430 (\u0442\u043e\u043a\u0435\u043d\u044b)",
  tabReport: "\u041e\u0442\u0447\u0435\u0442",
  gist: "\u0421\u0443\u0442\u044c \u0441\u0442\u0430\u0442\u044c\u0438",
  gistNotReady: "\u0421\u0443\u0442\u044c \u0441\u0442\u0430\u0442\u044c\u0438 \u043f\u043e\u043a\u0430 \u043d\u0435 \u0433\u043e\u0442\u043e\u0432\u0430.",
  pdfLen: "PDF (\u043a\u043e\u043b. \u0441\u0438\u043c\u0432\u043e\u043b\u043e\u0432",
  articleText: "\u0422\u0435\u043a\u0441\u0442 \u0441\u0442\u0430\u0442\u044c\u0438",
  splitBtn: "\u0420\u0430\u0437\u0431\u0438\u0442\u044c full_text \u043d\u0430 \u0447\u0430\u0441\u0442\u0438",
  reportBtn: "\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043e\u0442\u0447\u0435\u0442 \u043d\u0430 \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435",
  reprocessBtn: "\u041f\u0435\u0440\u0435\u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c (PDF + AI)",
  tokensPerPart: "\u0422\u043e\u043a\u0435\u043d\u043e\u0432 \u043d\u0430 \u0447\u0430\u0441\u0442\u044c",
  approxTokens: "\u041f\u0440\u0438\u0431\u043b\u0438\u0437\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439 total tokens",
  noFullTextFallback: "full_text \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442, \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u043c abstract \u0434\u043b\u044f \u043f\u0440\u0435\u0434\u0432\u0430\u0440\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0439 \u0440\u0430\u0437\u043c\u0435\u0442\u043a\u0438.",
  parts: "\u0427\u0430\u0441\u0442\u0438",
  emptyText: "\u0422\u0435\u043a\u0441\u0442 \u043f\u0443\u0441\u0442.",
  part: "\u0427\u0430\u0441\u0442\u044c",
  selectedPart: "\u0412\u044b\u0431\u0440\u0430\u043d\u043d\u0430\u044f \u0447\u0430\u0441\u0442\u044c",
  localMetrics: "\u041b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0435 \u043c\u0435\u0442\u0440\u0438\u043a\u0438 (\u044d\u0432\u0440\u0438\u0441\u0442\u0438\u043a\u0438)",
  localMetricsHint: "\u0412 API \u043f\u043e\u043a\u0430 \u043d\u0435\u0442 ML-\u044d\u043d\u0434\u043f\u043e\u0438\u043d\u0442\u0430 \u0434\u043b\u044f \u0438\u0437\u0432\u043b\u0435\u0447\u0435\u043d\u0438\u044f \u043c\u0435\u0442\u0440\u0438\u043a.",
  temps: "\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u044b (\u00b0C)",
  aiAnalysis: "AI \u0430\u043d\u0430\u043b\u0438\u0437 (\u0440\u0443\u0441\u0441\u043a\u0438\u0439)",
  aiNotReady: "\u0410\u043d\u0430\u043b\u0438\u0437 \u0435\u0449\u0451 \u043d\u0435 \u0433\u043e\u0442\u043e\u0432.",
  translation: "\u041f\u0435\u0440\u0435\u0432\u043e\u0434 (\u0440\u0443\u0441\u0441\u043a\u0438\u0439)",
  translationNotReady: "\u041f\u0435\u0440\u0435\u0432\u043e\u0434 \u0435\u0449\u0451 \u043d\u0435 \u0433\u043e\u0442\u043e\u0432.",
  processingError: "\u041e\u0448\u0438\u0431\u043a\u0430 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438",
  noTextForReport: "\u041d\u0435\u0442 \u0442\u0435\u043a\u0441\u0442\u0430 \u0434\u043b\u044f \u043e\u0442\u0447\u0435\u0442\u0430.",
  quickOverview: "\u0427\u0430\u0441\u0442\u0438 (\u0431\u044b\u0441\u0442\u0440\u044b\u0439 \u043e\u0431\u0437\u043e\u0440)",
  deletePaper: "\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0441\u0442\u0430\u0442\u044c\u044e",
  copyGist: "\u041a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0441\u0443\u0442\u044c",
  backToList: "\u041d\u0430\u0437\u0430\u0434 \u043a \u0441\u043f\u0438\u0441\u043a\u0443",
  copied: "\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u043e!",
  confirmDelete: "\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0441\u0442\u0430\u0442\u044c\u044e \u0438\u0437 \u0431\u0430\u0437\u044b?",
  unknown: "\u2014",
};

function approxTokenCount(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function splitByTokens(text: string, tokensPerPart: number): string[] {
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  if (!tokens.length) return [];
  const out: string[] = [];
  for (let i = 0; i < tokens.length; i += tokensPerPart) {
    out.push(tokens.slice(i, i + tokensPerPart).join(" "));
  }
  return out;
}

function localExtractMetrics(text: string) {
  const lower = text.toLowerCase();
  const keywords = ["nickel", "superalloy", "inconel", "hastelloy", "creep", "tensile", "fatigue", "yield", "temperature", "corrosion"];
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

function MarkdownText({ text }: { text: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} skipHtml>
        {text}
      </ReactMarkdown>
    </div>
  );
}

export default function PatentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("main");
  const [tokensPerPart, setTokensPerPart] = useState(350);
  const [activePartIndex, setActivePartIndex] = useState(0);

  const loadPaper = async () => {
    const paperId = Number(id);
    if (!paperId || Number.isNaN(paperId)) {
      setError(RU.invalidId);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    getPaperById(paperId)
      .then((p) => setPaper(p))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPaper();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const fullText = paper?.fullText ?? paper?.abstract ?? "";
  const hasFullTextOrPdf = Boolean((paper?.fullText && paper.fullText.trim().length > 0) || paper?.pdfUrl || paper?.pdfLocalPath);

  const parts = useMemo(() => {
    if (!paper) return [];
    const text = paper.fullText || paper.abstract || "";
    if (!text.trim()) return [];
    return splitByTokens(text, Math.max(50, tokensPerPart));
  }, [paper, tokensPerPart]);

  useEffect(() => {
    setActivePartIndex(0);
  }, [tokensPerPart]);

  const partMetrics = useMemo(() => {
    if (!parts.length) return null;
    return localExtractMetrics(parts[activePartIndex] ?? "");
  }, [parts, activePartIndex]);

  const onDelete = async () => {
    if (!paper) return;
    if (!window.confirm(RU.confirmDelete)) return;
    await deletePaper(paper.id);
    navigate("/papers");
  };

  const onReprocess = async () => {
    if (!paper) return;
    await reprocessPaperContent(paper.id);
    await loadPaper();
  };

  if (loading) return <p className="muted">{RU.loading}</p>;
  if (error) return <p className="error">{error}</p>;
  if (!paper) return <p className="muted">{RU.notFound}</p>;

  return (
    <div className="page">
      <p className="muted">
        <Link to="/dashboard">{RU.home}</Link> → <Link to="/papers">{RU.papers}</Link> → {paper.title}
      </p>

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>{paper.title}</h2>
        <div className="detail-grid">
          <p>
            <strong>{RU.authors}:</strong> {paper.authors.length ? paper.authors.slice(0, 4).join(", ") + (paper.authors.length > 4 ? "..." : "") : RU.unknown}
          </p>
          <p>
            <strong>{RU.source}:</strong> {paper.source}
          </p>
          <p>
            <strong>{RU.date}:</strong> {paper.publicationDate ? paper.publicationDate.slice(0, 10) : RU.unknown}
          </p>
          <p>
            <strong>{RU.journal}:</strong> {paper.journal ?? RU.unknown}
          </p>
          <p>
            <strong>DOI:</strong> {paper.doi ?? RU.unknown}
          </p>
          <p>
            <strong>{RU.keywords}:</strong> {paper.keywords.length ? paper.keywords.slice(0, 10).join(", ") : RU.unknown}
          </p>
          <p>
            <strong>{RU.status}:</strong> {getProcessingStatusLabel(paper.processingStatus)}
          </p>
          <p>
            <strong>{RU.fullText}:</strong> {hasFullTextOrPdf ? RU.yes : RU.no}
          </p>
          <p>
            <strong>URL:</strong>{" "}
            {paper.url ? (
              <a href={paper.url} target="_blank" rel="noreferrer" className="action-link">
                {RU.open}
              </a>
            ) : (
              RU.unknown
            )}
          </p>
          <p>
            <strong>PDF:</strong>{" "}
            {paper.pdfUrl || paper.pdfLocalPath ? (
              <a href={getPaperPdfUrl(paper.id)} target="_blank" rel="noreferrer" className="action-link">
                {RU.openPdf}
              </a>
            ) : (
              RU.unknown
            )}
          </p>
          <p>
            <strong>{RU.workerTask}:</strong> {paper.contentTaskId ?? RU.unknown}
          </p>
        </div>
      </div>

      <div className="tabs">
        <button className={`btn ${tab === "main" ? "btn-primary" : ""}`} onClick={() => setTab("main")}>
          {RU.tabMain}
        </button>
        <button className={`btn ${tab === "parts" ? "btn-primary" : ""}`} onClick={() => setTab("parts")}>
          {RU.tabParts}
        </button>
        <button className={`btn ${tab === "report" ? "btn-primary" : ""}`} onClick={() => setTab("report")}>
          {RU.tabReport}
        </button>
      </div>

      {tab === "main" && (
        <article className="panel">
          {paper.summaryRu ? (
            <>
              <h3 style={{ marginTop: 0 }}>{RU.gist}</h3>
              <p style={{ whiteSpace: "pre-wrap" }}>{paper.summaryRu}</p>
            </>
          ) : (
            <p className="muted">{RU.gistNotReady}</p>
          )}

          {(paper.pdfUrl || paper.pdfLocalPath) && (
            <>
              <h3 style={{ marginTop: 18 }}>
                {RU.pdfLen}: {paper.fullText?.length ?? 0})
              </h3>
              <iframe title="paper-pdf" src={getPaperPdfUrl(paper.id)} style={{ width: "100%", height: 640, border: "1px solid #e5e7eb", borderRadius: 8 }} />
              {paper.fullText && (
                <>
                  <h3 style={{ marginTop: 18 }}>{RU.articleText}</h3>
                  <MarkdownText text={paper.fullText} />
                </>
              )}
            </>
          )}

          <div style={{ marginTop: 12 }}>
            <button className="btn btn-primary" onClick={() => setTab("parts")}>
              {RU.splitBtn}
            </button>
            <button className="btn" style={{ marginLeft: 10 }} onClick={() => navigate(`/papers/${paper.id}/report`)}>
              {RU.reportBtn}
            </button>
            <button className="btn" style={{ marginLeft: 10 }} onClick={onReprocess}>
              {RU.reprocessBtn}
            </button>
          </div>
        </article>
      )}

      {tab === "parts" && (
        <article className="panel">
          <div className="filters">
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted">{RU.tokensPerPart}:</span>
              <input
                className="input"
                type="number"
                min={50}
                max={3000}
                value={tokensPerPart}
                onChange={(e) => setTokensPerPart(Number(e.target.value))}
                style={{ width: 120 }}
              />
            </label>
            <span className="muted">
              {RU.approxTokens}: {approxTokenCount(fullText)}
            </span>
          </div>

          {!paper.fullText && <p className="muted">{RU.noFullTextFallback}</p>}

          <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 12, alignItems: "start" }}>
            <div className="panel" style={{ padding: 12, boxShadow: "none" }}>
              <h3 style={{ marginTop: 0 }}>{RU.parts}</h3>
              {!parts.length ? (
                <p className="muted">{RU.emptyText}</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {parts.map((_, idx) => (
                    <button key={idx} className={`btn ${idx === activePartIndex ? "btn-primary" : ""}`} onClick={() => setActivePartIndex(idx)} style={{ justifyContent: "flex-start" }}>
                      {RU.part} {idx + 1}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="panel" style={{ padding: 12, boxShadow: "none" }}>
              <h3 style={{ marginTop: 0 }}>{RU.selectedPart}</h3>
              <p className="muted">
                Index: {activePartIndex + 1} / {parts.length}
              </p>
              <p style={{ whiteSpace: "pre-wrap" }}>{parts[activePartIndex] ?? ""}</p>

              <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "14px 0" }} />
              <h3 style={{ marginTop: 0 }}>{RU.localMetrics}</h3>
              <p className="muted">{RU.localMetricsHint}</p>

              {partMetrics && (
                <div className="detail-grid" style={{ marginTop: 10 }}>
                  <p>
                    <strong>Top keywords:</strong>{" "}
                    {partMetrics.topKeywords.length ? partMetrics.topKeywords.map(([k, v]) => `${k}=${v}`).join(", ") : RU.unknown}
                  </p>
                  <p>
                    <strong>{RU.temps}:</strong> {partMetrics.temps.length ? partMetrics.temps.join(", ") : RU.unknown}
                  </p>
                </div>
              )}
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

          {paper.processingError && (
            <p className="error" style={{ marginTop: 12 }}>
              {RU.processingError}: {paper.processingError}
            </p>
          )}

          {!parts.length ? (
            <p className="muted">{RU.noTextForReport}</p>
          ) : (
            <>
              <h3>{RU.quickOverview}</h3>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                {parts.slice(0, 8).map((part, idx) => {
                  const m = localExtractMetrics(part);
                  return (
                    <article className="panel" key={idx} style={{ boxShadow: "none", padding: 12 }}>
                      <p className="muted">
                        {RU.part} {idx + 1}
                      </p>
                      <p style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 13 }}>
                        {(m.topKeywords.length ? m.topKeywords.map(([k, v]) => `${k}:${v}`).join(", ") : "\u043c\u0435\u0442\u0440\u0438\u043a\u0438 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u044b") + "\n\n"}
                        {part.slice(0, 300)}...
                      </p>
                    </article>
                  );
                })}
              </div>
              {parts.length > 8 && <p className="muted">\u041f\u043e\u043a\u0430\u0437\u0430\u043d\u044b \u043f\u0435\u0440\u0432\u044b\u0435 8 \u0447\u0430\u0441\u0442\u0435\u0439.</p>}
            </>
          )}
        </article>
      )}

      <div className="actions">
        <button className="btn btn-danger" onClick={onDelete}>
          {RU.deletePaper}
        </button>
        <button
          className="btn"
          onClick={() => {
            navigator.clipboard.writeText(paper.summaryRu ?? "");
            alert(RU.copied);
          }}
        >
          {RU.copyGist}
        </button>
        <button className="btn" onClick={() => navigate("/papers")}>
          {RU.backToList}
        </button>
      </div>
    </div>
  );
}

