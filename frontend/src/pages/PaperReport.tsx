import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../api/client";
import { getPaperById } from "../api/papers";
import type { Paper } from "../types/paper";

type PaperReportData = {
  paper_id: number;
  title: string;
  authors: string[];
  journal: string | null;
  publication_date: string | null;
  doi: string | null;
  source: string;
  abstract_length: number;
  full_text_length: number;
  keywords_count: number;
  scores: {
    quality_score: number;
    completeness_score: number;
  };
  recommendations: string[];
  generated_at: string;
};

const RU = {
  invalidId: "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 ID \u0441\u0442\u0430\u0442\u044c\u0438",
  loading: "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u043e\u0442\u0447\u0451\u0442\u0430...",
  notFound: "\u0421\u0442\u0430\u0442\u044c\u044f \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430.",
  home: "\u0413\u043b\u0430\u0432\u043d\u0430\u044f",
  papers: "\u0421\u0442\u0430\u0442\u044c\u0438",
  card: "\u041a\u0430\u0440\u0442\u043e\u0447\u043a\u0430",
  report: "\u041e\u0442\u0447\u0451\u0442",
  reportTitle: "\u041e\u0442\u0447\u0451\u0442 \u043f\u043e \u0441\u0442\u0430\u0442\u044c\u0435",
  exportPdf: "\u042d\u043a\u0441\u043f\u043e\u0440\u0442 PDF",
  exportDocx: "\u042d\u043a\u0441\u043f\u043e\u0440\u0442 DOCX",
  exporting: "\u042d\u043a\u0441\u043f\u043e\u0440\u0442...",
  exportPdfError: "\u041e\u0448\u0438\u0431\u043a\u0430 \u044d\u043a\u0441\u043f\u043e\u0440\u0442\u0430 PDF",
  exportDocxError: "\u041e\u0448\u0438\u0431\u043a\u0430 \u044d\u043a\u0441\u043f\u043e\u0440\u0442\u0430 DOCX",
  basicInfo: "\u041e\u0441\u043d\u043e\u0432\u043d\u0430\u044f \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u044f",
  source: "\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a",
  authors: "\u0410\u0432\u0442\u043e\u0440\u044b",
  journal: "\u0416\u0443\u0440\u043d\u0430\u043b",
  pubDate: "\u0414\u0430\u0442\u0430 \u043f\u0443\u0431\u043b\u0438\u043a\u0430\u0446\u0438\u0438",
  quality: "\u041a\u0430\u0447\u0435\u0441\u0442\u0432\u043e",
  completeness: "\u041f\u043e\u043b\u043d\u043e\u0442\u0430",
  abstract: "\u0410\u043d\u043d\u043e\u0442\u0430\u0446\u0438\u044f",
  fullText: "\u041f\u043e\u043b\u043d\u044b\u0439 \u0442\u0435\u043a\u0441\u0442",
  keywords: "\u041a\u043b\u044e\u0447\u0435\u0432\u044b\u0435 \u0441\u043b\u043e\u0432\u0430",
  symbols: "\u0441\u0438\u043c\u0432\u043e\u043b\u043e\u0432",
  noAbstract: "\u0410\u043d\u043d\u043e\u0442\u0430\u0446\u0438\u044f \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442",
  noKeywords: "\u041a\u043b\u044e\u0447\u0435\u0432\u044b\u0435 \u0441\u043b\u043e\u0432\u0430 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u044e\u0442",
  recommendations: "\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u0438 \u043f\u043e \u0443\u043b\u0443\u0447\u0448\u0435\u043d\u0438\u044e",
  noRecommendations: "\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u0439 \u043d\u0435\u0442",
  generatedAt: "\u0421\u0433\u0435\u043d\u0435\u0440\u0438\u0440\u043e\u0432\u0430\u043d",
  openCard: "\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0443",
  backToList: "\u041a \u0441\u043f\u0438\u0441\u043a\u0443 \u0441\u0442\u0430\u0442\u0435\u0439",
  unknown: "\u2014",
} as const;

export default function PaperReport() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [report, setReport] = useState<PaperReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState<"pdf" | "docx" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const paperId = Number(id);
    if (!paperId || Number.isNaN(paperId)) {
      setError(RU.invalidId);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    Promise.all([getPaperById(paperId), apiClient.get<PaperReportData>(`/reports/paper/${paperId}`).catch(() => null)])
      .then(([paperData, reportRes]) => {
        setPaper(paperData);
        setReport(reportRes?.data || null);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [id]);

  const exportReport = async (format: "pdf" | "docx") => {
    if (!paper) return;
    setExporting(format);
    setError(null);
    try {
      const response = await apiClient.get(`/reports/paper/${paper.id}/${format}`, { responseType: "blob" });
      const type =
        format === "pdf"
          ? "application/pdf"
          : "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
      const blob = new Blob([response.data], { type });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `paper_${paper.id}_report.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(`${format === "pdf" ? RU.exportPdfError : RU.exportDocxError}: ${e.message}`);
    } finally {
      setExporting(null);
    }
  };

  if (loading) return <p className="muted">{RU.loading}</p>;
  if (error) return <p className="error">{error}</p>;
  if (!paper) return <p className="muted">{RU.notFound}</p>;

  const qualityScore = report?.scores?.quality_score || 0;
  const completenessScore = report?.scores?.completeness_score || 0;
  const recommendations = report?.recommendations || [];

  return (
    <div className="page">
      <p className="muted">
        <Link to="/dashboard">{RU.home}</Link> → <Link to="/papers">{RU.papers}</Link> → <Link to={`/papers/${paper.id}`}>{RU.card}</Link> → {RU.report}
      </p>

      <div className="page-head">
        <h2>{RU.reportTitle}</h2>
        <div className="actions">
          <button className="btn" onClick={() => exportReport("pdf")} disabled={exporting === "pdf"}>
            {exporting === "pdf" ? RU.exporting : RU.exportPdf}
          </button>
          <button className="btn" onClick={() => exportReport("docx")} disabled={exporting === "docx"}>
            {exporting === "docx" ? RU.exporting : RU.exportDocx}
          </button>
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{RU.basicInfo}</h3>
        <div className="detail-grid">
          <p>
            <strong>ID:</strong> {paper.id}
          </p>
          <p>
            <strong>{RU.source}:</strong> {paper.source}
          </p>
        </div>
        <h4 style={{ margin: "16px 0 8px" }}>{paper.title}</h4>
        {!!paper.authors.length && (
          <p>
            <strong>{RU.authors}:</strong> {paper.authors.join(", ")}
          </p>
        )}
        <div className="detail-grid">
          <p>
            <strong>{RU.journal}:</strong> {paper.journal || RU.unknown}
          </p>
          <p>
            <strong>{RU.pubDate}:</strong> {paper.publicationDate ? paper.publicationDate.slice(0, 10) : RU.unknown}
          </p>
        </div>
        {paper.doi && (
          <p>
            <strong>DOI:</strong> <code>{paper.doi}</code>
          </p>
        )}
      </div>

      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <article className="panel kpi-card">
          <h3>{RU.quality}</h3>
          <p className={`kpi ${qualityScore >= 70 ? "ok" : qualityScore >= 40 ? "" : "idle"}`}>{qualityScore}/100</p>
        </article>
        <article className="panel kpi-card">
          <h3>{RU.completeness}</h3>
          <p className={`kpi ${completenessScore >= 70 ? "ok" : completenessScore >= 40 ? "" : "idle"}`}>{completenessScore.toFixed(0)}%</p>
        </article>
        <article className="panel kpi-card">
          <h3>{RU.abstract}</h3>
          <p className="kpi">{report?.abstract_length || 0}</p>
          <p className="muted" style={{ fontSize: 12 }}>
            {RU.symbols}
          </p>
        </article>
        <article className="panel kpi-card">
          <h3>{RU.fullText}</h3>
          <p className="kpi">{report?.full_text_length || 0}</p>
          <p className="muted" style={{ fontSize: 12 }}>
            {RU.symbols}
          </p>
        </article>
        <article className="panel kpi-card">
          <h3>{RU.keywords}</h3>
          <p className="kpi">{report?.keywords_count || 0}</p>
        </article>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{RU.abstract}</h3>
        {paper.abstract ? <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{paper.abstract}</p> : <p className="muted">{RU.noAbstract}</p>}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{RU.keywords}</h3>
        {paper.keywords.length ? (
          <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{paper.keywords.join(", ")}</p>
        ) : (
          <p className="muted">{RU.noKeywords}</p>
        )}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{RU.recommendations}</h3>
        {recommendations.length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {recommendations.map((item, i) => (
              <li key={`${i}-${item.slice(0, 20)}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">{RU.noRecommendations}</p>
        )}
        {report?.generated_at && (
          <p className="muted" style={{ marginTop: 12 }}>
            {RU.generatedAt}: {new Date(report.generated_at).toLocaleString()}
          </p>
        )}
      </div>

      <div className="actions">
        <button className="btn" onClick={() => navigate(`/papers/${paper.id}`)}>
          {RU.openCard}
        </button>
        <button className="btn btn-primary" onClick={() => navigate("/papers")}>
          {RU.backToList}
        </button>
      </div>
    </div>
  );
}

