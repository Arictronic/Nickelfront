import { useEffect, useState } from "react";
import { apiClient } from "../api/client";

type TopItem = {
  name: string;
  count: number;
};

type QualityReport = {
  total: number;
  completeness: Record<string, { count: number; percent: number }>;
  averages: {
    avg_abstract_length: number;
    avg_keywords_count: number;
  };
  quality_score: {
    avg: number;
    min: number;
    max: number;
  };
};

type KeywordStats = {
  total_papers: number;
  papers_with_keywords: number;
  papers_with_10_plus_keywords: number;
  papers_with_1_to_9_keywords: number;
  papers_without_keywords: number;
  total_keyword_mentions: number;
  unique_keywords: number;
  rare_keywords: number;
  avg_keywords_per_paper: number;
  max_keywords_per_paper: number;
};

function normalizeQualityReport(data: any): QualityReport | null {
  if (!data) return null;
  const completeness = data.completeness ?? data.quality_metrics ?? {};
  const averages = data.averages ?? {
    avg_abstract_length: 0,
    avg_keywords_count: 0,
  };
  const quality_score = data.quality_score ?? { avg: 0, min: 0, max: 0 };

  return {
    total: data.total ?? 0,
    completeness,
    averages,
    quality_score,
  };
}

export default function Metrics() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [topKeywords, setTopKeywords] = useState<TopItem[]>([]);
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);
  const [keywordStats, setKeywordStats] = useState<KeywordStats | null>(null);
  const [keywordsExpanded, setKeywordsExpanded] = useState(false);

  useEffect(() => {
    void loadAnalytics();
  }, []);

  const loadAnalytics = async () => {
    setLoading(true);
    setError(null);

    try {
      const [keywordsRes, qualityRes, keywordStatsRes] = await Promise.all([
        apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=keywords&limit=100"),
        apiClient.get<QualityReport>("/analytics/metrics/quality-report"),
        apiClient.get<KeywordStats>("/analytics/metrics/keyword-stats"),
      ]);

      setTopKeywords(keywordsRes.data?.items ?? []);
      setQualityReport(normalizeQualityReport(qualityRes.data));
      setKeywordStats(keywordStatsRes.data ?? null);
    } catch (e: any) {
      setError(e.message || "Ошибка загрузки данных");
      console.error("Analytics error:", e);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="page">
        <div className="page-head">
          <h2>Метрики и Аналитика</h2>
        </div>
        <div className="panel">
          <p>Загрузка данных...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <div className="page-head">
          <h2>Метрики и Аналитика</h2>
          <button className="btn" onClick={loadAnalytics}>Повторить</button>
        </div>
        <div className="panel">
          <p className="error">{error}</p>
        </div>
      </div>
    );
  }

  const visibleKeywords = keywordsExpanded ? topKeywords : topKeywords.slice(0, 30);
  const keywordCoverage = keywordStats && keywordStats.total_papers > 0
    ? Math.round((keywordStats.papers_with_keywords / keywordStats.total_papers) * 100)
    : 0;

  return (
    <div className="page">
      <div className="page-head">
        <h2>Метрики и Аналитика</h2>
        <div className="actions">
          <button className="btn" onClick={loadAnalytics}>Обновить</button>
        </div>
      </div>

      {keywordStats && (
        <div className="panel">
          <h3>Словарь ключевых слов</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
            <div>
              <p className="muted">Уникальных терминов</p>
              <p className="kpi-status ok">{keywordStats.unique_keywords}</p>
            </div>
            <div>
              <p className="muted">Всего упоминаний</p>
              <p className="kpi-status">{keywordStats.total_keyword_mentions}</p>
            </div>
            <div>
              <p className="muted">Статей с keywords</p>
              <p className="kpi-status">{keywordCoverage}%</p>
            </div>
            <div>
              <p className="muted">Статей с 10+ keywords</p>
              <p className="kpi-status">{keywordStats.papers_with_10_plus_keywords}</p>
            </div>
            <div>
              <p className="muted">Редких терминов</p>
              <p className="kpi-status">{keywordStats.rare_keywords}</p>
            </div>
            <div>
              <p className="muted">Максимум на статью</p>
              <p className="kpi-status">{keywordStats.max_keywords_per_paper}</p>
            </div>
          </div>
        </div>
      )}

      <div className="panel">
        <h3>Топ ключевых слов <span className="muted">({topKeywords.length} из 100)</span></h3>
        {topKeywords.length > 0 ? (
          <>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {visibleKeywords.map((item, idx) => (
                <span
                  key={`${item.name}-${idx}`}
                  style={{
                    padding: "6px 12px",
                    background: `rgba(74, 108, 247, ${0.1 + (idx / Math.max(1, visibleKeywords.length)) * 0.35})`,
                    borderRadius: 16,
                    fontSize: 14,
                    color: "var(--text)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {item.name} <strong style={{ marginLeft: 4 }}>{item.count}</strong>
                </span>
              ))}
            </div>
            {topKeywords.length > 30 && (
              <button className="btn" style={{ marginTop: 12 }} onClick={() => setKeywordsExpanded((v) => !v)}>
                {keywordsExpanded ? "Свернуть" : "Развернуть дальше"}
              </button>
            )}
          </>
        ) : (
          <p className="muted">Нет данных</p>
        )}
      </div>

      {qualityReport && (
        <div className="panel">
          <h3>Детали качества данных</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 16 }}>
            <div>
              <p className="muted">Средняя длина аннотации</p>
              <p><strong>{(qualityReport.averages?.avg_abstract_length ?? 0).toFixed(0)}</strong> символов</p>
            </div>
            <div>
              <p className="muted">Среднее количество ключевых слов</p>
              <p><strong>{(qualityReport.averages?.avg_keywords_count ?? 0).toFixed(1)}</strong></p>
            </div>
            <div>
              <p className="muted">Качество (мин)</p>
              <p><strong>{qualityReport.quality_score?.min ?? 0}</strong></p>
            </div>
            <div>
              <p className="muted">Качество (макс)</p>
              <p><strong>{qualityReport.quality_score?.max ?? 0}</strong></p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
