import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, PieChart, Pie, Cell, LineChart, Line, ResponsiveContainer, Legend } from "recharts";
import { apiClient } from "../api/client";

const COLORS = ["#4a6cf7", "#00c49f", "#ffbb28", "#ff8042", "#8884d8"];

type AnalyticsSummary = {
  total_papers: number;
  papers_by_source: Record<string, number>;
  papers_with_embedding: number;
  embedding_coverage: number;
  avg_quality_score: number;
};

type TrendData = {
  period: string;
  count: number;
};

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
  
  // Summary data
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  
  // Trend data
  const [trend, setTrend] = useState<TrendData[]>([]);
  
  // Top items
  const [topJournals, setTopJournals] = useState<TopItem[]>([]);
  const [topKeywords, setTopKeywords] = useState<TopItem[]>([]);
  const [topAuthors, setTopAuthors] = useState<TopItem[]>([]);
  
  // Source distribution
  const [sourceDistribution, setSourceDistribution] = useState<Record<string, { count: number; percent: number }>>({});
  
  // Quality report
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);

  useEffect(() => {
    loadAnalytics();
  }, []);

  const loadAnalytics = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const [
        summaryRes,
        trendRes,
        journalsRes,
        keywordsRes,
        authorsRes,
        sourceRes,
        qualityRes,
      ] = await Promise.all([
        apiClient.get<AnalyticsSummary>("/analytics/metrics/summary"),
        apiClient.get<{ trend: TrendData[] }>("/analytics/metrics/trend?group_by=month&limit=12"),
        apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=journals&limit=10"),
        apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=keywords&limit=15"),
        apiClient.get<{ items: TopItem[] }>("/analytics/metrics/top?item_type=authors&limit=10"),
        apiClient.get<{ distribution: Record<string, { count: number; percent: number }> }>("/analytics/metrics/source-distribution"),
        apiClient.get<QualityReport>("/analytics/metrics/quality-report"),
      ]);

      setSummary(summaryRes.data ?? null);
      setTrend(trendRes.data?.trend ?? []);
      setTopJournals(journalsRes.data?.items ?? []);
      setTopKeywords(keywordsRes.data?.items ?? []);
      setTopAuthors(authorsRes.data?.items ?? []);
      setSourceDistribution(sourceRes.data?.distribution ?? {});
      setQualityReport(normalizeQualityReport(qualityRes.data));
    } catch (e: any) {
      setError(e.message || "Ошибка загрузки данных");
      console.error("Analytics error:", e);
    } finally {
      setLoading(false);
    }
  };

  const sourcePieData = Object.entries(sourceDistribution ?? {}).map(([name, data]) => ({
    name,
    value: data.count,
  }));

  const qualityData = qualityReport
    ? Object.entries(qualityReport.completeness ?? {}).map(([key, data]) => ({
        name: key.replace("with_", "").replace("_", " ").toUpperCase(),
        percent: data.percent,
      }))
    : [];

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

  return (
    <div className="page">
      <div className="page-head">
        <h2>Метрики и Аналитика</h2>
        <div className="actions">
          <button className="btn" onClick={loadAnalytics}>Обновить</button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
        <article className="panel kpi-card">
          <h3>Всего статей</h3>
          <p className="kpi">{summary?.total_papers || 0}</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>CORE</h3>
          <p className="kpi">{summary?.papers_by_source?.CORE || 0}</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>arXiv</h3>
          <p className="kpi">{summary?.papers_by_source?.arXiv || 0}</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>С эмбеддингами</h3>
          <p className="kpi">{summary?.papers_with_embedding || 0}</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Покрытие эмбеддингами</h3>
          <p className="kpi">{summary?.embedding_coverage || 0}%</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Среднее качество</h3>
          <p className="kpi">{summary?.avg_quality_score || 0}</p>
        </article>
      </div>

      {/* Charts Row 1 */}
      <div className="chart-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))" }}>
        <article className="panel">
          <h3>Тренд публикаций (по месяцам)</h3>
          {trend.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={trend}>
                <XAxis dataKey="period" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="count" stroke="#4a6cf7" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">Нет данных</p>
          )}
        </article>

        <article className="panel">
          <h3>Распределение по источникам</h3>
          {sourcePieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={sourcePieData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label
                >
                  {sourcePieData.map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">Нет данных</p>
          )}
        </article>
      </div>

      {/* Charts Row 2 */}
      <div className="chart-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))" }}>
        <article className="panel">
          <h3>Топ журналов</h3>
          {topJournals.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={topJournals}>
                <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={80} />
                <YAxis />
                <Tooltip />
                <Bar dataKey="count" fill="#4a6cf7" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">Нет данных</p>
          )}
        </article>

        <article className="panel">
          <h3>Полнота данных</h3>
          {qualityData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={qualityData} layout="vertical">
                <XAxis type="number" domain={[0, 100]} />
                <YAxis dataKey="name" type="category" width={100} />
                <Tooltip formatter={(value: number) => `${value.toFixed(1)}%`} />
                <Bar dataKey="percent" fill="#00c49f" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="muted">Нет данных</p>
          )}
        </article>
      </div>

      {/* Top Keywords */}
      <div className="panel">
        <h3>Топ ключевых слов</h3>
        {topKeywords.length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {topKeywords.map((item, idx) => (
              <span
                key={idx}
                style={{
                  padding: "6px 12px",
                  background: `rgba(74, 108, 247, ${0.1 + (idx / topKeywords.length) * 0.4})`,
                  borderRadius: 16,
                  fontSize: 14,
                  color: "#1e293b",
                }}
              >
                {item.name} <strong style={{ marginLeft: 4 }}>{item.count}</strong>
              </span>
            ))}
          </div>
        ) : (
          <p className="muted">Нет данных</p>
        )}
      </div>

      {/* Top Authors */}
      <div className="panel">
        <h3>Топ авторов</h3>
        {topAuthors.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Автор</th>
                <th>Количество статей</th>
              </tr>
            </thead>
            <tbody>
              {topAuthors.map((author, idx) => (
                <tr key={idx}>
                  <td>{idx + 1}</td>
                  <td>{author.name}</td>
                  <td>{author.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Нет данных</p>
        )}
      </div>

      {/* Quality Details */}
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
