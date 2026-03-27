import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getPaperById } from "../api/papers";
import type { Paper } from "../types/paper";
import { apiClient } from "../api/client";

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
      setError("Некорректный ID статьи");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    
    Promise.all([
      getPaperById(paperId),
      apiClient.get<PaperReportData>(`/reports/paper/${paperId}`).catch(() => null),
    ])
      .then(([paperData, reportRes]) => {
        setPaper(paperData);
        setReport(reportRes?.data || null);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [id]);

  const handleExportPDF = async () => {
    if (!paper) return;
    
    setExporting("pdf");
    setError(null);
    
    try {
      const response = await apiClient.get(`/reports/paper/${paper.id}/pdf`, {
        responseType: "blob",
      });
      
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `paper_${paper.id}_report.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(`Ошибка экспорта PDF: ${e.message}`);
    } finally {
      setExporting(null);
    }
  };

  const handleExportDOCX = async () => {
    if (!paper) return;
    
    setExporting("docx");
    setError(null);
    
    try {
      const response = await apiClient.get(`/reports/paper/${paper.id}/docx`, {
        responseType: "blob",
      });
      
      const blob = new Blob([response.data], { 
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" 
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `paper_${paper.id}_report.docx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(`Ошибка экспорта DOCX: ${e.message}`);
    } finally {
      setExporting(null);
    }
  };

  if (loading) return <p className="muted">Загрузка отчёта...</p>;
  if (error) return <p className="error">{error}</p>;
  if (!paper) return <p className="muted">Статья не найдена.</p>;

  const qualityScore = report?.scores?.quality_score || 0;
  const completenessScore = report?.scores?.completeness_score || 0;
  const recommendations = report?.recommendations || [];

  return (
    <div className="page">
      <p className="muted">
        <Link to="/dashboard">Главная</Link> → <Link to="/papers">Статьи</Link> → <Link to={`/papers/${paper.id}`}>Карточка</Link> → Отчёт
      </p>

      <div className="page-head">
        <h2>Отчёт по статье</h2>
        <div className="actions">
          <button 
            className="btn" 
            onClick={handleExportPDF} 
            disabled={exporting === "pdf"}
          >
            {exporting === "pdf" ? "Экспорт..." : "📄 Экспорт PDF"}
          </button>
          <button 
            className="btn" 
            onClick={handleExportDOCX} 
            disabled={exporting === "docx"}
          >
            {exporting === "docx" ? "Экспорт..." : "📝 Экспорт DOCX"}
          </button>
        </div>
      </div>

      {/* Основная информация */}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Основная информация</h3>
        <div className="detail-grid">
          <p><strong>ID:</strong> {paper.id}</p>
          <p><strong>Источник:</strong> {paper.source}</p>
        </div>
        
        <h4 style={{ margin: "16px 0 8px" }}>{paper.title}</h4>
        
        {paper.authors && paper.authors.length > 0 && (
          <p><strong>Авторы:</strong> {paper.authors.join(", ")}</p>
        )}
        
        <div className="detail-grid">
          <p><strong>Журнал:</strong> {paper.journal || "—"}</p>
          <p><strong>Дата публикации:</strong> {paper.publicationDate ? paper.publicationDate.slice(0, 10) : "—"}</p>
        </div>
        
        {paper.doi && (
          <p><strong>DOI:</strong> <code>{paper.doi}</code></p>
        )}
      </div>

      {/* Метрики качества */}
      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <article className="panel kpi-card">
          <h3>Качество</h3>
          <p className={`kpi ${qualityScore >= 70 ? "ok" : qualityScore >= 40 ? "" : "idle"}`}>
            {qualityScore}/100
          </p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Полнота</h3>
          <p className={`kpi ${completenessScore >= 70 ? "ok" : completenessScore >= 40 ? "" : "idle"}`}>
            {completenessScore.toFixed(0)}%
          </p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Аннотация</h3>
          <p className="kpi">{report?.abstract_length || 0}</p>
          <p className="muted" style={{ fontSize: 12 }}>символов</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Полный текст</h3>
          <p className="kpi">{report?.full_text_length || 0}</p>
          <p className="muted" style={{ fontSize: 12 }}>символов</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Ключевые слова</h3>
          <p className="kpi">{report?.keywords_count || 0}</p>
        </article>
      </div>

      {/* Аннотация */}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Аннотация</h3>
        {paper.abstract ? (
          <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{paper.abstract}</p>
        ) : (
          <p className="muted">Аннотация отсутствует</p>
        )}
      </div>

      {/* Ключевые слова */}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Ключевые слова</h3>
        {paper.keywords && paper.keywords.length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {paper.keywords.map((kw, idx) => (
              <span
                key={idx}
                style={{
                  padding: "6px 12px",
                  background: "#e0e7ff",
                  borderRadius: 16,
                  fontSize: 14,
                  color: "#1e293b",
                }}
              >
                {kw}
              </span>
            ))}
          </div>
        ) : (
          <p className="muted">Ключевые слова не указаны</p>
        )}
      </div>

      {/* Рекомендации */}
      {recommendations.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>📋 Рекомендации по улучшению</h3>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {recommendations.map((rec, idx) => (
              <li key={idx} style={{ marginBottom: 8 }}>{rec}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Полный текст */}
      {paper.fullText && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Полный текст</h3>
          <div style={{ 
            maxHeight: 400, 
            overflowY: "auto", 
            padding: 12, 
            background: "#f8fafc", 
            borderRadius: 8,
            fontSize: 14,
            lineHeight: 1.6,
          }}>
            <p style={{ whiteSpace: "pre-wrap" }}>{paper.fullText}</p>
          </div>
        </div>
      )}

      {/* Действия */}
      <div className="actions">
        <button className="btn" onClick={() => navigate(`/papers/${paper.id}`)}>
          Назад к карточке
        </button>
        <button className="btn btn-primary" onClick={() => navigate("/papers")}>
          К списку статей
        </button>
      </div>

      <p className="muted" style={{ marginTop: 16, fontSize: 12 }}>
        Отчёт сгенерирован автоматически на основе данных статьи. 
        {report?.generated_at && ` Время генерации: ${new Date(report.generated_at).toLocaleString("ru-RU")}`}
      </p>
    </div>
  );
}
