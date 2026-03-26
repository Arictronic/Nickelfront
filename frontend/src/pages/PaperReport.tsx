import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getPaperById } from "../api/papers";
import type { Paper } from "../types/paper";

function splitByTokens(text: string, tokensPerPart: number): string[] {
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return [];
  const parts: string[] = [];
  for (let i = 0; i < tokens.length; i += tokensPerPart) {
    parts.push(tokens.slice(i, i + tokensPerPart).join(" "));
  }
  return parts;
}

function approxTokenCount(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).length;
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
  const nums = (text.match(/\b\d+(?:\.\d+)?\b/g) ?? []).slice(0, 50);

  const topKeywords = Object.entries(found)
    .sort((a, b) => b[1] - a[1])
    .filter(([, v]) => v > 0)
    .slice(0, 8);

  return { topKeywords, temps, numbersSample: nums };
}

export default function PaperReport() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [tokensPerPart, setTokensPerPart] = useState(350);
  const [activePartIndex, setActivePartIndex] = useState(0);
  const [prompt, setPrompt] = useState("Извлеки метрики металлов: температуры, свойства, условия испытаний.");
  const [generatedAt, setGeneratedAt] = useState<number | null>(null);

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

  useEffect(() => setActivePartIndex(0), [tokensPerPart]);

  const activePart = parts[activePartIndex] ?? "";

  const activeMetrics = useMemo(() => {
    if (!activePart) return null;
    return localExtractMetrics(activePart);
  }, [activePart]);

  const overallReport = useMemo(() => {
    if (!parts.length) return null;
    const agg: Record<string, number> = {};
    const temps: string[] = [];
    for (const part of parts) {
      const m = localExtractMetrics(part);
      for (const [k, v] of m.topKeywords) agg[k] = (agg[k] ?? 0) + v;
      temps.push(...m.temps);
    }

    const topKeywords = Object.entries(agg).sort((a, b) => b[1] - a[1]).slice(0, 10);
    return { topKeywords, temps };
  }, [parts]);

  const onGenerate = () => {
    // В текущем бэке нет ML-эндпоинта. Кнопка оставлена под будущую интеграцию.
    setGeneratedAt(Date.now());
  };

  if (loading) return <p className="muted">Загрузка статьи...</p>;
  if (error) return <p className="error">{error}</p>;
  if (!paper) return <p className="muted">Статья не найдена.</p>;

  return (
    <div className="page">
      <p className="muted">
        <Link to="/dashboard">Главная</Link> → <Link to="/papers">Статьи</Link> → Отчет
      </p>

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>{paper.title}</h2>
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
          <span className="muted">Примерный total tokens: {approxTokenCount(fullText)}</span>
        </div>
        <div className="filters" style={{ marginTop: 10 }}>
          <textarea
            className="input"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            style={{ width: "100%", minHeight: 80, resize: "vertical" }}
          />
          <button className="btn btn-primary" onClick={onGenerate}>
            Сформировать отчет (превью)
          </button>
        </div>
        <p className="muted" style={{ marginTop: 8 }}>
          {generatedAt ? `Сгенерировано: ${new Date(generatedAt).toLocaleTimeString("ru-RU")}` : "Нажмите кнопку для фиксации времени генерации."}
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: 12, alignItems: "start" }}>
        <div className="panel" style={{ padding: 12, boxShadow: "none" }}>
          <h3 style={{ marginTop: 0 }}>Части текста</h3>
          {parts.length === 0 ? (
            <p className="muted">Нет текста для разбиения.</p>
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

        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Вывод по активной части</h3>
          {!activePart ? (
            <p className="muted">Выберите часть слева.</p>
          ) : (
            <>
              <p className="muted">
                Часть {activePartIndex + 1} / {parts.length}
              </p>
              <article style={{ whiteSpace: "pre-wrap" }}>
                <div className="panel" style={{ padding: 12, boxShadow: "none" }}>
                  <p className="muted" style={{ margin: 0 }}>
                    Текст (кратко):
                  </p>
                  <p style={{ marginTop: 8, marginBottom: 0 }}>
                    {activePart.slice(0, 700)}
                    {activePart.length > 700 ? "…" : ""}
                  </p>
                </div>
              </article>

              <div style={{ marginTop: 12 }} className="detail-grid">
                <p>
                  <strong>Top keywords:</strong>{" "}
                  {activeMetrics?.topKeywords.length ? activeMetrics.topKeywords.map(([k, v]) => `${k}:${v}`).join(", ") : "—"}
                </p>
                <p>
                  <strong>Температуры:</strong> {activeMetrics?.temps.length ? activeMetrics.temps.join(", ") : "—"}
                </p>
              </div>
            </>
          )}

          <hr style={{ border: "none", borderTop: "1px solid #e5e7eb", margin: "14px 0" }} />

          <h3 style={{ marginTop: 0 }}>Общий отчет (агрегация по частям)</h3>
          {!overallReport ? (
            <p className="muted">Отчет пока недоступен.</p>
          ) : (
            <div className="detail-grid">
              <p>
                <strong>Top keywords:</strong>{" "}
                {overallReport.topKeywords.length ? overallReport.topKeywords.map(([k, v]) => `${k}:${v}`).join(", ") : "—"}
              </p>
              <p>
                <strong>Температуры найдено:</strong> {overallReport.temps.length}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="actions">
        <button className="btn" onClick={() => navigate(`/papers/${paper.id}`)}>
          Назад к карточке
        </button>
      </div>
    </div>
  );
}

