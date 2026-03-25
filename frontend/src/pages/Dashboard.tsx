import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, PieChart, Pie, Cell } from "recharts";
import { startParsing } from "../api/patents";
import { usePatentStore } from "../store/patentStore";

const COLORS = ["#0088FE", "#00C49F", "#FFBB28"];

export default function Dashboard() {
  const patents = usePatentStore((s) => s.patents);
  const [status, setStatus] = useState("остановлен");
  const [updatedAt, setUpdatedAt] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setUpdatedAt(new Date()), 30000);
    return () => clearInterval(id);
  }, []);

  const lineData = patents
    .map((p) => ({ date: p.publicationDate, count: 1 }))
    .sort((a, b) => a.date.localeCompare(b.date));
  const pieData = Object.entries(
    patents.reduce<Record<string, number>>((acc, p) => {
      acc[p.category] = (acc[p.category] ?? 0) + 1;
      return acc;
    }, {})
  ).map(([name, value]) => ({ name, value }));
  const todayString = new Date().toISOString().slice(0, 10);
  const todayCount = patents.filter((p) => p.publicationDate === todayString).length;
  const activeCount = patents.filter((p) => p.status === "active").length;
  const weekCount = patents.filter((p) => new Date(p.publicationDate) >= new Date(Date.now() - 7 * 86400000)).length;

  return (
    <div className="page">
      <div className="page-head">
        <h2>Dashboard</h2>
        <div className="actions">
          <button className="btn" onClick={() => setUpdatedAt(new Date())}>
            Обновить данные
          </button>
          <button
            className="btn btn-primary"
            onClick={async () => {
              setStatus("работает");
              await startParsing({ patent_number: "RU123456", options: {} }).catch(() => setStatus("ошибка"));
            }}
          >
            Запустить парсинг
          </button>
        </div>
      </div>
      <div className="kpi-grid">
        <article className="panel kpi-card">
          <h3>Всего патентов</h3>
          <p className="kpi">{patents.length}</p>
        </article>
        <article className="panel kpi-card">
          <h3>За сегодня</h3>
          <p className="kpi">{todayCount}</p>
        </article>
        <article className="panel kpi-card">
          <h3>За неделю</h3>
          <p className="kpi">{weekCount}</p>
        </article>
        <article className="panel kpi-card">
          <h3>Активные / Парсинг</h3>
          <p className={`kpi-status ${status === "работает" ? "ok" : "idle"}`}>
            {activeCount} / {status}
          </p>
        </article>
      </div>
      <div className="chart-grid">
        <article className="panel">
          <h3>Патенты по датам</h3>
          <LineChart width={520} height={230} data={lineData}>
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="count" stroke="#4a6cf7" />
          </LineChart>
        </article>
        <article className="panel">
          <h3>Топ категорий</h3>
          <PieChart width={350} height={230}>
            <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={80}>
              {pieData.map((_, index) => (
                <Cell key={index} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </article>
      </div>
      <article className="panel">
        <h3>Последние добавленные</h3>
        <table className="table">
          <thead>
            <tr>
              <th>№</th>
              <th>Название</th>
              <th>Дата публикации</th>
            </tr>
          </thead>
          <tbody>
            {[...patents]
              .sort((a, b) => b.publicationDate.localeCompare(a.publicationDate))
              .slice(0, 5)
              .map((p) => (
                <tr key={p.id}>
                  <td>{p.patentNumber}</td>
                  <td>{p.title}</td>
                  <td>{p.publicationDate}</td>
                </tr>
              ))}
          </tbody>
        </table>
        <p className="muted">Обновлено: {updatedAt.toLocaleTimeString("ru-RU")}</p>
      </article>
    </div>
  );
}
