import { Link } from "react-router-dom";
import type { Paper } from "../../types/paper";

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString("ru-RU");
}

function hasText(value: string | null | undefined): boolean {
  return Boolean(value && value.trim());
}

function badgeClass(ok: boolean): string {
  return ok ? "active" : "neutral";
}

interface Props {
  papers: Paper[];
}

export default function RecentPapersPanel({ papers }: Props) {
  return (
    <section className="panel dashboard-recent-panel">
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Последние данные</span>
          <h3>Последние документы</h3>
        </div>
        <Link className="btn" to="/database">Вся база</Link>
      </div>
      <div className="dashboard-recent-list">
        {papers.length === 0 ? (
          <div className="dashboard-empty-box">
            <strong>Пока нет документов</strong>
            <p>Запустите парсинг — последние результаты появятся здесь с бейджами качества.</p>
          </div>
        ) : papers.slice(0, 8).map((paper) => {
          const hasPdf = Boolean(paper.pdfUrl || paper.pdfLocalPath || paper.hasPdf);
          const hasFullText = Boolean(paper.hasFullText || hasText(paper.fullText));
          const hasEmbedding = ["embedding_ready", "ready", "ready_with_fallback", "completed"].includes(paper.processingStatus || "");
          return (
            <article key={paper.id} className="dashboard-recent-card">
              <div>
                <Link to={`/papers/${paper.id}`} className="dashboard-recent-title">{paper.title}</Link>
                <p>{paper.source} · {formatDate(paper.publicationDate)} · {paper.doi || "DOI нет"}</p>
              </div>
              <div className="dashboard-quality-badges">
                <span className={`status ${badgeClass(hasText(paper.abstract))}`}>Аннотация</span>
                <span className={`status ${badgeClass(hasFullText)}`}>Полный текст</span>
                <span className={`status ${badgeClass(hasPdf)}`}>PDF</span>
                <span className={`status ${badgeClass(hasEmbedding)}`}>Эмбеддинг</span>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
