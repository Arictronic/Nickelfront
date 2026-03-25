import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import PatentCard from "../components/patents/PatentCard";
import { usePatentStore } from "../store/patentStore";

export default function PatentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const patents = usePatentStore((s) => s.patents);
  const setPatents = usePatentStore((s) => s.setPatents);
  const [tab, setTab] = useState<"description" | "claims" | "pdf" | "analytics">("description");
  const [zoom, setZoom] = useState(100);
  const patent = useMemo(() => patents.find((p) => String(p.id) === id), [id, patents]);

  if (!patent) return <p>Патент не найден</p>;

  return (
    <div className="page">
      <p className="muted">
        <Link to="/dashboard">Главная</Link> → <Link to="/patents">Патенты</Link> → {patent.title}
      </p>
      <PatentCard patent={patent} />
      <div className="tabs">
        <button className={`btn ${tab === "description" ? "btn-primary" : ""}`} onClick={() => setTab("description")}>
          Описание
        </button>
        <button className={`btn ${tab === "claims" ? "btn-primary" : ""}`} onClick={() => setTab("claims")}>
          Формула
        </button>
        <button className={`btn ${tab === "pdf" ? "btn-primary" : ""}`} onClick={() => setTab("pdf")}>
          PDF
        </button>
        <button className={`btn ${tab === "analytics" ? "btn-primary" : ""}`} onClick={() => setTab("analytics")}>
          Аналитика
        </button>
      </div>
      <article className="panel">
        {tab === "description" && <p>{patent.abstract}</p>}
        {tab === "claims" && <p>{patent.claims}</p>}
        {tab === "pdf" && <p className="muted">Встроенный PDF viewer (mock) с zoom-контролом ниже.</p>}
        {tab === "analytics" && <p>Похожие патенты и ML-метрики отображаются как mock до интеграции с ML API.</p>}
      </article>
      <div className="actions">
        <button className="btn" onClick={() => alert("Редактирование: mock-форма будет подключена к API позже")}>
          Редактировать
        </button>
        <button className="btn" onClick={() => navigator.clipboard.writeText(patent.abstract)}>
          Копировать текст
        </button>
        <button className="btn" onClick={() => alert("Скачивание PDF подключится после добавления url в API")}>
          Скачать PDF
        </button>
        <button className="btn" onClick={() => navigate(`/patents?category=${encodeURIComponent(patent.category)}`)}>
          Найти похожие
        </button>
        <button
          className="btn btn-danger"
          onClick={() => {
            if (!window.confirm("Удалить патент?")) return;
            setPatents(patents.filter((p) => p.id !== patent.id));
            navigate("/patents");
          }}
        >
          Удалить
        </button>
      </div>
      {tab === "pdf" && (
        <article className="panel">
          <div className="actions">
            <button className="btn" onClick={() => setZoom((z) => Math.max(50, z - 10))}>
              - Масштаб
            </button>
            <span className="muted">{zoom}%</span>
            <button className="btn" onClick={() => setZoom((z) => Math.min(200, z + 10))}>
              + Масштаб
            </button>
          </div>
          <div className="pdf-box" style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top left" }}>
            <iframe
              title="Patent PDF mock"
              src="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
              width="700"
              height="480"
            />
          </div>
        </article>
      )}
    </div>
  );
}
