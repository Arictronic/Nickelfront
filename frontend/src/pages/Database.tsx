import { useEffect, useState } from "react";
import { getPapersCount } from "../api/papers";

export default function Database() {
  const [allCount, setAllCount] = useState(0);
  const [coreCount, setCoreCount] = useState(0);
  const [arxivCount, setArxivCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [all, core, arxiv] = await Promise.all([
        getPapersCount(),
        getPapersCount("CORE"),
        getPapersCount("arXiv")
      ]);
      setAllCount(all);
      setCoreCount(core);
      setArxivCount(arxiv);
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
          <p>
            <strong>CORE:</strong> {coreCount}
          </p>
          <p>
            <strong>arXiv:</strong> {arxivCount}
          </p>
        </div>
      </div>

      <div className="panel">
        <h3>Таблицы в базе данных</h3>
        <div className="detail-grid">
          <p>
            <strong>papers</strong> — основные данные статей
          </p>
          <p>
            <strong>users</strong> — пользователи системы
          </p>
          <p>
            <strong>refresh_tokens</strong> — токены обновления сессий
          </p>
          <p>
            <strong>alembic_version</strong> — версия миграций БД
          </p>
        </div>
      </div>

      <div className="panel">
        <h3>Доступные API endpoints</h3>
        <p className="muted">
          <br />
          • <code>GET /api/v1/papers</code> — список статей с пагинацией<br />
          • <code>POST /api/v1/papers/search</code> — поиск по названию/аннотации/ключевым словам<br />
          • <code>POST /api/v1/papers/parse</code> — запуск парсинга<br />
          • <code>GET /api/v1/papers/id/{id}</code> — получение статьи по ID<br />
          • <code>DELETE /api/v1/papers/id/{id}</code> — удаление статьи
        </p>
        <div className="actions" style={{ marginTop: 10 }}>
          <a className="btn btn-primary" href="/papers" style={{ textDecoration: 'none' }}>
            Перейти к списку статей
          </a>
          <a className="btn" href="/vector-search" style={{ textDecoration: 'none' }}>
            Векторный поиск
          </a>
          <a className="btn" href="/docs" target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none' }}>
            Swagger документация
          </a>
        </div>
      </div>
    </div>
  );
}

