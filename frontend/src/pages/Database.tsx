import { useEffect, useState } from "react";
import { getPapersCount } from "../api/papers";
import { Link } from "react-router-dom";

export default function Database() {
  const [allCount, setAllCount] = useState(0);
  const [coreCount, setCoreCount] = useState(0);
  const [arxivCount, setArxivCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setError(null);
    try {
      const [all, core, arxiv] = await Promise.all([getPapersCount("all"), getPapersCount("CORE"), getPapersCount("arXiv")]);
      setAllCount(all);
      setCoreCount(core);
      setArxivCount(arxiv);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    refresh().catch(() => null);
  }, []);

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
        <h3>Таблицы (текущее состояние бэка)</h3>
        <div className="detail-grid">
          <p>
            <strong>papers</strong> — {allCount} строк
          </p>
          <p>
            <strong>CORE</strong> — {coreCount}
          </p>
          <p>
            <strong>arXiv</strong> — {arxivCount}
          </p>
          <p>
            <strong>patent_tasks</strong> — есть endpoint для задач, но они относятся к “patent_number” (в текущем бэке нет papers-status)
          </p>
        </div>
      </div>

      <div className="panel">
        <h3>Какие данные доступны с фронта</h3>
        <p className="muted">
          Для статей сейчас используются:
          <br />
          <br />
          • `GET /api/v1/papers?limit&offset&source` — список (с пагинацией).<br />
          • `POST /api/v1/papers/search` — поиск по title/abstract/keywords.<br />
          • `POST /api/v1/papers/parse` и `POST /api/v1/papers/parse-all` — запуск celery-парсинга.<br />
          • `GET /api/v1/papers/id/{id}` и `DELETE /api/v1/papers/id/{id}` — карточка и удаление.
        </p>
        <div className="actions" style={{ marginTop: 10 }}>
          <Link className="btn btn-primary" to="/papers">
            Перейти к списку статей
          </Link>
          <Link className="btn" to="/jobs">
            Посмотреть статус парсинга
          </Link>
          <Link className="btn" to="/vector-search">
            Поиск по базе
          </Link>
        </div>
      </div>
    </div>
  );
}

