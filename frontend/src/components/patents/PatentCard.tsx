import type { Patent } from "../../types/patent";

export default function PatentCard({ patent }: { patent: Patent }) {
  return (
    <section className="panel">
      <h2>{patent.title}</h2>
      <div className="detail-grid">
        <p>Номер: {patent.patentNumber}</p>
        <p>Заявитель: {patent.applicant}</p>
        <p>Дата подачи: {patent.filingDate}</p>
        <p>Дата публикации: {patent.publicationDate}</p>
        <p>Категория: {patent.category}</p>
        <p>Страна: {patent.country}</p>
        <p>Статус: {patent.status}</p>
      </div>
    </section>
  );
}
