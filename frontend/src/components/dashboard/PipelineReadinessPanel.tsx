import type { DashboardCounts, DashboardPipeline } from "../../types/dashboard";

function clamp(value: number): number {
  return Math.max(0, Math.min(100, Number(value || 0)));
}

function missing(total: number, ready: number): number {
  return Math.max(0, total - ready);
}

interface Props {
  counts: DashboardCounts;
  pipeline: DashboardPipeline;
}

export default function PipelineReadinessPanel({ counts, pipeline }: Props) {
  const rows = [
    { label: "Метаданные", value: pipeline.metadataPercent, hint: `${counts.metadataReady}/${counts.totalPapers}` },
    { label: "Аннотации", value: pipeline.abstractPercent, hint: `${counts.withAbstract}/${counts.totalPapers}` },
    { label: "Полный текст", value: pipeline.fullTextPercent, hint: `${counts.withFullText}/${counts.totalPapers}` },
    { label: "PDF доступен", value: pipeline.pdfPercent, hint: `${counts.withPdf}/${counts.totalPapers}` },
    { label: "Контент-блоки", value: pipeline.contentPartsPercent, hint: `${counts.withContentParts}/${counts.totalPapers}` },
    { label: "Контент готов", value: pipeline.contentReadyPercent, hint: `${counts.contentReady}/${counts.totalPapers}` },
    { label: "Эмбеддинги в БД", value: pipeline.embeddingPercent, hint: `${counts.withEmbeddings}/${counts.totalPapers}` },
    { label: "Векторный индекс", value: pipeline.vectorPercent, hint: `${counts.vectorIndexed}/${counts.withEmbeddings} из эмбеддингов` },
    { label: "RAG-индексе", value: pipeline.ragPercent, hint: `${counts.ragReady}/${counts.ragCandidates} кандидатов` },
    { label: "Qwen-анализ", value: pipeline.qwenPercent, hint: `${counts.qwenReady}/${counts.totalPapers}` },
  ];

  const recommendations = [
    missing(counts.totalPapers, counts.withFullText) > 0 ? `${missing(counts.totalPapers, counts.withFullText)} документов без полного текста` : null,
    missing(counts.totalPapers, counts.withContentParts) > 0 ? `${missing(counts.totalPapers, counts.withContentParts)} документов без контент-блоков` : null,
    missing(counts.totalPapers, counts.withEmbeddings) > 0 ? `${missing(counts.totalPapers, counts.withEmbeddings)} документов без эмбеддингов` : null,
    Math.max(0, counts.withEmbeddings - counts.vectorIndexed) > 0 ? `${Math.max(0, counts.withEmbeddings - counts.vectorIndexed)} документов с эмбеддингами не подтверждены в векторном индексе` : null,
    Math.max(0, counts.ragCandidates - counts.ragReady) > 0 ? `${Math.max(0, counts.ragCandidates - counts.ragReady)} RAG-кандидатов не подтверждены в RAG-индексе` : null,
    counts.contentQueued > 0 ? `${counts.contentQueued} документов в очереди обработки PDF и контента` : null,
    counts.processingErrors > 0 ? `${counts.processingErrors} документов с ошибкой обработки` : null,
  ].filter(Boolean) as string[];

  return (
    <section className="panel dashboard-readiness-panel">
      <div className="dashboard-panel-head">
        <div>
          <span className="eyebrow">Готовность данных</span>
          <h3>Готовность обработки</h3>
        </div>
        <span className="dashboard-score-ring">{clamp(pipeline.qualityPercent).toFixed(0)}%</span>
      </div>
      <div className="dashboard-readiness-list">
        {rows.map((row) => (
          <div key={row.label} className="dashboard-readiness-row">
            <div className="dashboard-readiness-label">
              <span>{row.label}</span>
              <small>{row.hint}</small>
            </div>
            <div className="dashboard-readiness-track" aria-label={`${row.label}: ${row.value}%`}>
              <div style={{ width: `${clamp(row.value)}%` }} />
            </div>
            <strong>{clamp(row.value).toFixed(1)}%</strong>
          </div>
        ))}
      </div>
      <div className="dashboard-next-actions">
        <strong>Что улучшить дальше</strong>
        {recommendations.length ? (
          <ul>
            {recommendations.slice(0, 5).map((item) => <li key={item}>{item}</li>)}
          </ul>
        ) : (
          <p className="muted">Критичных провалов готовности не видно.</p>
        )}
      </div>
    </section>
  );
}
