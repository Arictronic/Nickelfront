import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, Tooltip, PieChart, Pie, Cell } from "recharts";
import { useAuthStore } from "../store/authStore";
import { getPapersCount, getPapersList } from "../api/papers";
import type { Paper } from "../types/paper";

const COLORS = ["#0088FE", "#00C49F", "#FFBB28", "#A855F7", "#14B8A6"];

export default function Landing() {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const [totalPapers, setTotalPapers] = useState<number | null>(null);
  const [latest, setLatest] = useState<Paper[]>([]);

  useEffect(() => {
    Promise.all([getPapersCount("all"), getPapersList({ limit: 60, offset: 0, source: "all" })])
      .then(([count, items]) => {
        setTotalPapers(count);
        setLatest(items);
      })
      .catch(() => {
        // If backend isn't reachable, show empty charts; main navigation stays usable.
      });
  }, []);

  const lineData = useMemo(() => {
    const counts = latest.reduce<Record<string, number>>((acc, p) => {
      const day = (p.publicationDate ?? "").slice(0, 10);
      if (!day) return acc;
      acc[day] = (acc[day] ?? 0) + 1;
      return acc;
    }, {});

    return Object.entries(counts)
      .map(([date, count]) => ({ date, count }))
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(-10);
  }, [latest]);

  const pieData = useMemo(() => {
    const bySource = latest.reduce<Record<string, number>>((acc, p) => {
      const key = String(p.source ?? "unknown");
      acc[key] = (acc[key] ?? 0) + 1;
      return acc;
    }, {});

    return Object.entries(bySource).map(([name, value]) => ({ name, value }));
  }, [latest]);

  const primaryAction = () => {
    if (isAuthenticated) navigate("/dashboard");
    else navigate("/login");
  };

  return (
    <div className="page">
      <div className="panel">
        <div className="page-head" style={{ alignItems: "flex-start" }}>
          <div>
            <h2 style={{ marginTop: 0 }}>Парсинг и анализ научных статей</h2>
            <p className="muted" style={{ maxWidth: 760 }}>
              Nickelfront хранит и каталогизирует статьи по материаловедению (никелевые сплавы, жаропрочные сплавы, суперсплавы),
              затем готовит данные для ML-анализа и отчетов. На главной странице показаны графики метрик и интерфейс поиска.
            </p>
            <p className="muted">
              В базе: <strong>{totalPapers ?? "—"}</strong> статей
            </p>
          </div>
          <div className="actions">
            <button className="btn btn-primary" onClick={primaryAction}>
              {isAuthenticated ? "Войти в систему" : "Авторизация"}
            </button>
          </div>
        </div>
      </div>

      <div className="chart-grid">
        <article className="panel">
          <h3>Метрика: рост набора по publication_date</h3>
          <LineChart width={520} height={230} data={lineData.length ? lineData : [{ date: "—", count: 0 }]}>
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="count" stroke="#4a6cf7" />
          </LineChart>
        </article>
        <article className="panel">
          <h3>Метрика: источники (последние)</h3>
          <PieChart width={350} height={230}>
            <Pie
              data={pieData.length ? pieData : [{ name: "нет данных", value: 1 }]}
              dataKey="value"
              nameKey="name"
              outerRadius={80}
            >
              {(pieData.length ? pieData : [{ name: "нет данных", value: 1 }]).map((_, index) => (
                <Cell key={index} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </article>
      </div>

      <div className="panel">
        <h3>Что умеет система (текущий функционал)</h3>
        <p className="muted">
          1) Запуск парсинга статей с `arXiv/CORE` в бэке (страница <strong>Dashboard</strong>).<br />
          2) Просмотр, поиск и удаление статей из базы (страница <strong>Статьи</strong>).<br />
          3) Страница <strong>Векторный поиск</strong> пока использует `/papers/search` как fallback (реальные эмбеддинги нужно добавить в API).
        </p>
      </div>
    </div>
  );
}

