import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getBackendRootUrl } from "../api/client";
import { getPapersCount } from "../api/papers";
import { PAPER_SOURCES } from "../types/paper";

export default function Database() {
  const [allCount, setAllCount] = useState(0);
  const [sourceCounts, setSourceCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const allPromise = getPapersCount();
      const sourcePromises = PAPER_SOURCES.map(async (source) => [source, await getPapersCount(source)] as const);
      const [allResult, sourceResults] = await Promise.allSettled([
        allPromise,
        Promise.allSettled(sourcePromises),
      ]);

      if (allResult.status === "fulfilled") {
        setAllCount(allResult.value);
      } else {
        setAllCount(0);
      }

      const nextSourceCounts: Record<string, number> = {};
      let failedSources = 0;
      if (sourceResults.status === "fulfilled") {
        for (const result of sourceResults.value) {
          if (result.status === "fulfilled") {
            const [source, count] = result.value;
            nextSourceCounts[source] = count;
          } else {
            failedSources += 1;
          }
        }
      } else {
        failedSources = PAPER_SOURCES.length;
      }
      setSourceCounts(nextSourceCounts);

      if (allResult.status === "rejected" && failedSources === PAPER_SOURCES.length) {
        setError(allResult.reason?.message || "Ошибка загрузки данных БД");
      } else if (allResult.status === "rejected" || failedSources > 0) {
        setError(`Часть счётчиков не загрузилась. Ошибок по источникам: ${failedSources}.`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  if (loading) {
    return (
      <div className="page">
        <div className="page-head">
          <h2>База данных</h2>
        </div>
        <div className="panel">
          <p>Загрузка данных...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>База данных</h2>
        <div className="actions">
          <button className="btn btn-primary" onClick={() => refresh()}>
            Обновить
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="panel">
        <h3>Статистика по статьям</h3>
        <div className="detail-grid">
          <p>
            <strong>Всего статей:</strong> {allCount}
          </p>
          {PAPER_SOURCES.map((source) => (
            <p key={source}>
              <strong>{source}:</strong> {sourceCounts[source] ?? 0}
            </p>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3>Таблицы в базе данных</h3>
        <p className="muted">
          Список таблиц больше не захардкожен во frontend, чтобы не вводить в заблуждение после миграций.
          Фактическую структуру БД проверяй через Alembic/PostgreSQL или отдельный admin endpoint.
        </p>
      </div>

      <div className="panel">
        <h3>Доступные API endpoints</h3>
        <p className="muted">
          <br />
          • <code>GET /api/v1/papers</code> — список статей с пагинацией
          <br />
          • <code>POST /api/v1/papers/search</code> — поиск по названию/аннотации/ключевым словам
          <br />
          • <code>POST /api/v1/papers/parse</code> — запуск парсинга
          <br />
          • <code>GET /api/v1/papers/id/{"{id}"}</code> — получение статьи по ID
          <br />
          • <code>DELETE /api/v1/papers/id/{"{id}"}</code> — удаление статьи
        </p>
        <div className="actions" style={{ marginTop: 10 }}>
          <Link className="btn btn-primary" to="/papers" style={{ textDecoration: "none" }}>
            Перейти к списку статей
          </Link>
          <Link className="btn" to="/vector-search" style={{ textDecoration: "none" }}>
            Векторный поиск
          </Link>
          <a className="btn" href={`${getBackendRootUrl()}/docs`} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
            Swagger документация
          </a>
        </div>
      </div>
    </div>
  );
}
