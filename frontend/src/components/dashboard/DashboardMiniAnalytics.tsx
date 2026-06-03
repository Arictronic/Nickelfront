import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardSourceStatus } from "../../types/dashboard";

export type TrendData = {
  period: string;
  count: number;
};

export type TopItem = {
  name: string;
  count: number;
};

interface Props {
  trend: TrendData[];
  keywords: TopItem[];
  sources: DashboardSourceStatus[];
}

function compactPeriod(value: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (!Number.isNaN(date.getTime())) {
    return date.toLocaleDateString("ru-RU", { month: "short", year: "2-digit" });
  }
  return value.slice(0, 7);
}

const chartTick = { fontSize: 11, fill: "var(--muted)" };
const chartTooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "12px",
  color: "var(--text)",
};

export default function DashboardMiniAnalytics({ trend, keywords, sources }: Props) {
  const sourceBars = sources
    .filter((source) => source.papersCount > 0)
    .sort((a, b) => b.papersCount - a.papersCount)
    .slice(0, 8)
    .map((source) => ({ name: source.name, count: source.papersCount }));
  const trendData = trend.map((item) => ({ ...item, periodLabel: compactPeriod(item.period) }));

  return (
    <section className="panel dashboard-mini-analytics">
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Краткая аналитика</span>
          <h3>Мини-аналитика</h3>
        </div>
        <Link className="btn" to="/metrics">Подробнее</Link>
      </div>
      <div className="dashboard-mini-grid">
        <div className="dashboard-mini-chart">
          <strong>Тренд публикаций</strong>
          {trendData.length ? (
            <ResponsiveContainer width="100%" height={190}>
              <BarChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis dataKey="periodLabel" tick={chartTick} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                <YAxis tick={chartTick} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                <Tooltip contentStyle={chartTooltipStyle} cursor={{ fill: "var(--primary-muted)" }} />
                <Bar dataKey="count" fill="var(--primary)" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="muted">Нет данных по тренду.</p>}
        </div>
        <div className="dashboard-mini-chart">
          <strong>Источники</strong>
          {sourceBars.length ? (
            <ResponsiveContainer width="100%" height={190}>
              <BarChart data={sourceBars} layout="vertical" margin={{ left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
                <XAxis type="number" tick={chartTick} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                <YAxis dataKey="name" type="category" width={90} tick={chartTick} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                <Tooltip contentStyle={chartTooltipStyle} cursor={{ fill: "var(--success-bg)" }} />
                <Bar dataKey="count" fill="var(--success)" radius={[0, 8, 8, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="muted">Нет данных по источникам.</p>}
        </div>
      </div>
      <div className="dashboard-keyword-strip">
        <strong>Тематика базы:</strong>
        {keywords.length ? keywords.slice(0, 12).map((item) => (
          <span key={item.name} className="dashboard-keyword-chip">{item.name} <b>{item.count}</b></span>
        )) : <span className="muted">ключевые слова пока не загружены</span>}
      </div>
    </section>
  );
}
