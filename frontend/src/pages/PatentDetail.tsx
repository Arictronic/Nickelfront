import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deletePaper, getPaperById } from "../api/papers";
import type { Paper } from "../types/paper";

type Tab = "description" | "textParts" | "report";

function approxTokenCount(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function splitByTokens(text: string, tokensPerPart: number): string[] {
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return [];
  const parts: string[] = [];
  for (let i = 0; i < tokens.length; i += tokensPerPart) {
    parts.push(tokens.slice(i, i + tokensPerPart).join(" "));
  }
  return parts;
}

function localExtractMetrics(text: string) {
  // Очень простая локальная имитация метрик.
  const lower = text.toLowerCase();
  const keywords = ["nickel", "superalloy", "inconel", "hastelloy", "creep", "tensile", "fatigue", "yield", "temperature", "corrosion"];
  const found: Record<string, number> = {};
  for (const k of keywords) {
    const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
    const m = lower.match(re);
    found[k] = m ? m.length : 0;
  }

  const temps = (text.match(/(\d+(?:\.\d+)?)\s*(?:°\s*)?c/gi) ?? []).slice(0, 20);
  const nums = (text.match(/\b\d+(?:\.\d+)?\b/g) ?? []).slice(0, 50);

  const topKeywords = Object.entries(found)
    .sort((a, b) => b[1] - a[1])
    .filter(([, v]) => v > 0)
    .slice(0, 8);

  return {
    topKeywords,
    temps,
    numbersSample: nums,
  };
}

export default function PatentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [tab, setTab] = useState<Tab>("description");

  // Токен-разбиение
  const [tokensPerPart, setTokensPerPart] = useState(350);
  const [activePartIndex, setActivePartIndex] = useState(0);

  const [prompt, setPrompt] = useState("Извлеки метрики металлов: составы/температуры/свойства и связанные условия.");
  const [reportGeneratedAt, setReportGeneratedAt] = useState<number | null>(null);

  useEffect(() => {
    const paperId = Number(id);
    if (!paperId || Number.isNaN(paperId)) {
      setError("Некорректный ID статьи");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    getPaperById(paperId)
      .then((p) => setPaper(p))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [id]);

  const fullText = paper?.fullText ?? paper?.abstract ?? "";

  const parts = useMemo(() => {
    if (!paper) return [];
    const text = paper.fullText ? paper.fullText : paper.abstract ?? "";
    if (!text || text.trim().length === 0) return [];
    return splitByTokens(text, Math.max(50, tokensPerPart));
  }, [paper, tokensPerPart]);

  useEffect(() => {
    setActivePartIndex(0);
  }, [tokensPerPart]);

  const partMetrics = useMemo(() => {
    if (!paper) return null;
    if (!parts.length) return null;
    const partText = parts[activePartIndex] ?? "";
    return localExtractMetrics(partText);
  }, [paper, parts, activePartIndex]);

  const overallReport = useMemo(() => {
    if (!paper || !parts.length) return null;
    // Агрегация по частям
    const agg: Record<string, number> = {};
    const temps: string[] = [];
    for (const part of parts) {
      const m = localExtractMetrics(part);
      for (const [k, v] of m.topKeywords) agg[k] = (agg[k] ?? 0) + v;
      temps.push(...m.temps);
    }
    const topKeywords = Object.entries(agg).sort((a, b) => b[1] - a[1]).slice(0, 10);
    return {
      topKeywords,
      temps,
    };
  }, [paper, parts]);

  const onGenerateReport = () => {
    if (!paper) return;
    navigate(`/papers/${paper.id}/report`);
  };

  const onDelete = async () => {
    if (!paper) return;
    if (!window.confirm("Удалить статью из базы?")) return;
    await deletePaper(paper.id);
    navigate("/papers");
  };

  if (loading) return <p className="muted">Загрузка статьи...</p>;
  if (error) return <p className="error">{error}</p>;
  if (!paper) return <p className="muted">Статья не найдена.</p>;

  return (
    <div className="page">
      <p className="muted">
        <Link to="/dashboard">Главная</Link> → <Link to="/papers">Статьи</Link> → {paper.title}
      </p>

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>{paper.title}</h2>
        <div className="detail-grid">
          <p>
            <strong>Авторы:</strong> {paper.authors.length ? paper.authors.slice(0, 4).join(", ") + (paper.authors.length > 4 ? "…" : "") : "—"}
          </p>
          <p>
            <strong>Источник:</strong> {paper.source}
          </p>
          <p>
            <strong>Дата:</strong> {paper.publicationDate ? paper.publicationDate.slice(0, 10) : "—"}
          </p>
          <p>
            <strong>Журнал:</strong> {paper.journal ?? "—"}
          </p>
          <p>
            <strong>DOI:</strong> {paper.doi ?? "—"}
          </p>
          <p>
            <strong>Ключевые слова:</strong> {paper.keywords.length ? paper.keywords.slice(0, 10).join(", ") : "—"}
          </p>
          <p>
            <strong>full_text:</strong> {paper.fullText ? "Есть" : "Нет"}
          </p>
          <p>
            <strong>URL:</strong>{" "}
            {paper.url ? (
              <a href={paper.url} target="_blank" rel="noreferrer" className="action-link">
                Открыть
              </a>
            ) : (
              "—"
            )}
          </p>
        </div>
      </div>

      <div className="tabs">
        <button className={`btn ${tab === "description" ? "btn-primary" : ""}`} onClick={() => setTab("description")}>
          Описание
        </button>
        <button className={`btn ${tab === "textParts" ? "btn-primary" : ""}`} onClick={() => setTab("textParts")}>
          Части текста (токены)
        </button>
        <button className={`btn ${tab === "report" ? "btn-primary" : ""}`} onClick={() => setTab("report")}>
          Отчет
        </button>
      </div>

      {tab === "description" && (
        <article className="panel">
          <h3>Abstract</h3>
          {paper.abstract ? <p>{paper.abstract}</p> : <p className="muted">Abstract отсутствует.</p>}
          <div style={{ marginTop: 12 }}>
            <button className="btn btn-primary" onClick={() => setTab("textParts")}>
              Разбить full_text на части
            </button>
            <button className="btn" style={{ marginLeft: 10 }} onClick={onGenerateReport}>
              Открыть отчет на отдельной странице
            </button>
          </div>
        </article>
      )}

      {tab === "textParts" && (
        <article className="panel">
          <div className="filters">
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="muted">Токенов на часть:</span>
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
            <span className="muted">Приблизительный total tokens: {approxTokenCount(fullText)} </span>
          </div>

          {paper.fullText ? null : <p className="muted">full_text отсутствует, используем abstract для предварительной разметки.</p>}

          <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 12, alignItems: "start" }}>
            <div className="panel" style={{ padding: 12, boxShadow: "none" }}>
              <h3 style={{ marginTop: 0 }}>Части</h3>
              {parts.length === 0 ? (
                <p className="muted">Текст пуст.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {parts.map((_, idx) => (
                    <button
                      key={idx}
                      className={`btn ${idx === activePartIndex ? "btn-primary" : ""}`}
                      onClick={() => setActivePartIndex(idx)}
                      style={{ justifyContent: "flex-start" }}
                    >
                      Часть {idx + 1}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div className="panel" style={{ padding: 12, boxShadow: "none" }}>
                <h3 style={{ marginTop: 0 }}>Выбранная часть</h3>
                <p className="muted">Index: {activePartIndex + 1} / {parts.length}</p>
                <p style={{ whiteSpace: "pre-wrap" }}>{parts[activePartIndex] ?? ""}</p>
                <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "14px 0" }} />
                <h3 style={{ marginTop: 0 }}>Локальные метрики (эвристики)</h3>
                <p className="muted">В API пока нет ML-эндпоинта для извлечения метрик, поэтому это эвристики по ключевым словам.</p>
                {partMetrics && (
                  <div>
                    <div className="detail-grid" style={{ marginTop: 10 }}>
                      <p>
                        <strong>Top keywords:</strong>
                        {partMetrics.topKeywords.length ? (
                          <span> {partMetrics.topKeywords.map(([k, v]) => `${k}=${v}`).join(", ")}</span>
                        ) : (
                          " —"
                        )}
                      </p>
                      <p>
                        <strong>Температуры (°C):</strong> {partMetrics.temps.length ? partMetrics.temps.join(", ") : "—"}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </article>
      )}

      {tab === "report" && (
        <article className="panel">
          <div className="filters">
            <textarea
              className="input"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              style={{ width: "100%", minHeight: 80, resize: "vertical" }}
            />
            <button className="btn btn-primary" onClick={onGenerateReport}>
              Сформировать отчет (превью)
            </button>
          </div>

          {!parts.length ? (
            <p className="muted">Нет текста для отчета.</p>
          ) : (
            <div>
              <p className="muted">
                Сгенерировано: {reportGeneratedAt ? new Date(reportGeneratedAt).toLocaleTimeString("ru-RU") : "не выполнено"}
              </p>
              <h3>Общий отчет (превью)</h3>
              {overallReport && (
                <div className="detail-grid">
                  <p>
                    <strong>Top keywords:</strong>{" "}
                    {overallReport.topKeywords.length ? overallReport.topKeywords.map(([k, v]) => `${k}=${v}`).join(", ") : "—"}
                  </p>
                  <p>
                    <strong>Температуры (найдено):</strong> {overallReport.temps.length}
                  </p>
                </div>
              )}
              <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "14px 0" }} />
              <h3>Части (быстрый обзор)</h3>
              {parts.slice(0, 8).map((part, idx) => {
                const m = localExtractMetrics(part);
                return (
                  <div key={idx} style={{ marginBottom: 14 }}>
                    <p className="muted">Часть {idx + 1}</p>
                    <p style={{ whiteSpace: "pre-wrap" }}>
                      {(m.topKeywords.length ? m.topKeywords.map(([k, v]) => `${k}:${v}`).join(", ") : "метрики не найдены") + "\n\n"}
                      {part.slice(0, 220)}
                      {part.length > 220 ? "…" : ""}
                    </p>
                  </div>
                );
              })}
              {parts.length > 8 && <p className="muted">Показаны первые 8 частей.</p>}
            </div>
          )}
        </article>
      )}

      <div className="actions">
        <button className="btn" onClick={onDelete}>
          Удалить статью
        </button>
        <button className="btn" onClick={() => navigator.clipboard.writeText(paper.abstract ?? "")}>
          Копировать abstract
        </button>
        <button className="btn" onClick={() => navigate("/papers")}>
          Назад к списку
        </button>
      </div>
    </div>
  );
}
