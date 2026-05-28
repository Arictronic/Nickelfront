import type { DashboardCounts, DashboardJobsSummary, DashboardPipeline } from "../../types/dashboard";

function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(Math.max(0, Math.round(value || 0)));
}

function percent(value: number): string {
  return `${Math.max(0, Math.min(100, Number(value || 0))).toFixed(1)}%`;
}

interface Props {
  counts: DashboardCounts;
  pipeline: DashboardPipeline;
  jobs: DashboardJobsSummary;
}

export default function DashboardKpiGrid({ counts, pipeline, jobs }: Props) {
  const cards = [
    { label: "Документов", value: formatNumber(counts.totalPapers), hint: `+${formatNumber(counts.todayPapers)} сегодня`, tone: "primary" },
    { label: "Полный текст", value: formatNumber(counts.withFullText), hint: percent(pipeline.fullTextPercent), tone: "success" },
    { label: "Контент-блоки", value: formatNumber(counts.withContentParts), hint: percent(pipeline.contentPartsPercent), tone: "neutral" },
    { label: "Эмбеддинги", value: formatNumber(counts.withEmbeddings), hint: percent(pipeline.embeddingPercent), tone: "success" },
    { label: "Векторный индекс", value: formatNumber(counts.vectorIndexed), hint: `${percent(pipeline.vectorPercent)} от эмбеддингов`, tone: "primary" },
    { label: "RAG-индексе", value: formatNumber(counts.ragReady), hint: `${percent(pipeline.ragPercent)} кандидатов`, tone: "primary" },
    { label: "Qwen-анализ", value: formatNumber(counts.qwenReady), hint: percent(pipeline.qwenPercent), tone: "neutral" },
    { label: "Активных задач", value: formatNumber(jobs.active), hint: `очередь: ${formatNumber(jobs.queued)}`, tone: jobs.active ? "warning" : "neutral" },
    { label: "Ошибок обработки", value: formatNumber(counts.processingErrors + jobs.failedRecent), hint: `${formatNumber(counts.contentQueued)} в обработке`, tone: counts.processingErrors || jobs.failedRecent ? "danger" : "success" },
    { label: "Качество базы", value: percent(pipeline.qualityPercent), hint: "метаданные/текст/вектор/RAG", tone: "primary" },
  ];

  return (
    <section className="dashboard-kpi-grid">
      {cards.map((card) => (
        <article key={card.label} className={`dashboard-kpi-card tone-${card.tone}`}>
          <span>{card.label}</span>
          <strong>{card.value}</strong>
          <small>{card.hint}</small>
        </article>
      ))}
    </section>
  );
}
