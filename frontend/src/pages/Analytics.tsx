import { useEffect, useMemo, useState } from "react";
import { BarChart, Bar, PieChart, Pie, XAxis, YAxis, Tooltip, Cell } from "recharts";
import { usePatentStore } from "../store/patentStore";

export default function Analytics() {
  const patents = usePatentStore((s) => s.patents);
  const [period, setPeriod] = useState<"year" | "five" | "all">("all");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  useEffect(() => {
    const raw = localStorage.getItem("analyticsView");
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as {
        period?: "year" | "five" | "all";
        activeCategory?: string | null;
        from?: string;
        to?: string;
      };
      if (parsed.period) setPeriod(parsed.period);
      setActiveCategory(parsed.activeCategory ?? null);
      setFrom(parsed.from ?? "");
      setTo(parsed.to ?? "");
    } catch {
      // ignore invalid stored data
    }
  }, []);

  const filteredByPeriod = useMemo(() => {
    if (period === "all") return patents;
    const now = new Date();
    const years = period === "year" ? 1 : 5;
    return patents.filter((p) => new Date(p.publicationDate) >= new Date(now.getFullYear() - years, now.getMonth(), now.getDate()));
  }, [patents, period]);

  const filtered = useMemo(() => {
    return filteredByPeriod.filter((p) => {
      if (from && p.publicationDate < from) return false;
      if (to && p.publicationDate > to) return false;
      return true;
    });
  }, [filteredByPeriod, from, to]);

  const byYear = Object.entries(
    filtered.reduce<Record<string, number>>((acc, p) => {
      const y = p.publicationDate.slice(0, 4);
      acc[y] = (acc[y] ?? 0) + 1;
      return acc;
    }, {})
  )
    .map(([year, count]) => ({ year, count }))
    .sort((a, b) => a.year.localeCompare(b.year));

  const byCategory = Object.entries(
    filtered.reduce<Record<string, number>>((acc, p) => {
      acc[p.category] = (acc[p.category] ?? 0) + 1;
      return acc;
    }, {})
  ).map(([name, value]) => ({ name, value }));

  const byCountry = Object.entries(
    filtered.reduce<Record<string, number>>((acc, p) => {
      if (activeCategory && p.category !== activeCategory) return acc;
      acc[p.country] = (acc[p.country] ?? 0) + 1;
      return acc;
    }, {})
  )
    .map(([country, count]) => ({ country, count }))
    .sort((a, b) => b.count - a.count);

  const byApplicant = Object.entries(
    filtered.reduce<Record<string, number>>((acc, p) => {
      acc[p.applicant] = (acc[p.applicant] ?? 0) + 1;
      return acc;
    }, {})
  )
    .map(([applicant, count]) => ({ applicant, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  const byMonth = Array.from({ length: 12 }, (_, i) => {
    const month = String(i + 1).padStart(2, "0");
    const count = filtered.filter((p) => p.publicationDate.slice(5, 7) === month).length;
    return { month, count };
  });

  const saveView = () => {
    localStorage.setItem("analyticsView", JSON.stringify({ period, activeCategory, from, to }));
    alert("Текущий вид сохранен");
  };

  const exportPngMock = () => {
    const blob = new Blob([JSON.stringify({ byYear, byCategory, byCountry, byApplicant }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "analytics-report-mock.png";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>Аналитика</h2>
        <div className="actions">
          <button className={`btn ${period === "year" ? "btn-primary" : ""}`} onClick={() => setPeriod("year")}>
            За год
          </button>
          <button className={`btn ${period === "five" ? "btn-primary" : ""}`} onClick={() => setPeriod("five")}>
            За 5 лет
          </button>
          <button className={`btn ${period === "all" ? "btn-primary" : ""}`} onClick={() => setPeriod("all")}>
            За все время
          </button>
          <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          <button className="btn" onClick={saveView}>
            Сохранить вид
          </button>
          <button className="btn" onClick={() => window.print()}>
            Экспорт PDF
          </button>
          <button className="btn" onClick={exportPngMock}>
            Экспорт PNG
          </button>
        </div>
      </div>
      <div className="chart-grid">
        <article className="panel">
          <h3>Патенты по годам</h3>
          <BarChart width={520} height={250} data={byYear}>
            <XAxis dataKey="year" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="count" fill="#4a6cf7" />
          </BarChart>
        </article>
        <article className="panel">
          <h3>По категориям (клик = фильтрация)</h3>
          <PieChart width={350} height={250}>
            <Pie
              data={byCategory}
              dataKey="value"
              nameKey="name"
              outerRadius={80}
              onClick={(entry) => setActiveCategory(entry.name === activeCategory ? null : String(entry.name))}
            >
              {byCategory.map((entry, index) => (
                <Cell key={entry.name} fill={["#4a6cf7", "#0ea5e9", "#14b8a6", "#f59e0b", "#ef4444"][index % 5]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
          <p className="muted">Текущая категория: {activeCategory ?? "Все"}</p>
        </article>
      </div>
      <article className="panel">
        <h3>По странам</h3>
        <BarChart width={900} height={240} data={byCountry} layout="vertical">
          <XAxis type="number" />
          <YAxis type="category" dataKey="country" width={60} />
          <Tooltip />
          <Bar dataKey="count" fill="#0ea5e9" />
        </BarChart>
      </article>
      <article className="panel">
        <h3>Топ 10 заявителей</h3>
        <BarChart width={900} height={240} data={byApplicant}>
          <XAxis dataKey="applicant" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="count" fill="#14b8a6" />
        </BarChart>
        <table className="table">
          <thead>
            <tr>
              <th>Заявитель</th>
              <th>Патентов</th>
            </tr>
          </thead>
          <tbody>
            {byApplicant.map((item) => (
              <tr key={item.applicant}>
                <td>{item.applicant}</td>
                <td>{item.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
      <article className="panel">
        <h3>Тепловая карта по месяцам</h3>
        <div className="heatmap">
          {byMonth.map((m) => (
            <div key={m.month} className="heat-cell" style={{ backgroundColor: `rgba(37,99,235,${Math.min(0.15 + m.count * 0.15, 1)})` }}>
              <span>{m.month}</span>
              <strong>{m.count}</strong>
            </div>
          ))}
        </div>
      </article>
    </div>
  );
}
