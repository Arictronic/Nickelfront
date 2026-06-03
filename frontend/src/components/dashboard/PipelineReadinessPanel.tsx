import type { DashboardCounts, DashboardPipeline } from "../../types/dashboard";

function clamp(value: number): number {
  return Math.max(0, Math.min(100, Number(value || 0)));
}

function missing(total: number, ready: number): number {
  return Math.max(0, total - ready);
}

type ReadinessRow = {
  label: string;
  value: number;
  hint: string;
  applicable?: boolean;
  unknown?: boolean;
};

function readinessValue(row: ReadinessRow): string {
  if (row.unknown) return "проверка недоступна";
  if (row.applicable === false) return "не применимо";
  return `${clamp(row.value).toFixed(1)}%`;
}

function readinessAria(row: ReadinessRow): string {
  if (row.unknown) return `${row.label}: проверка недоступна`;
  if (row.applicable === false) return `${row.label}: не применимо`;
  return `${row.label}: ${row.value}%`;
}

interface Props {
  counts: DashboardCounts;
  pipeline: DashboardPipeline;
}

export default function PipelineReadinessPanel({ counts, pipeline }: Props) {
  const hasPapers = counts.totalPapers > 0;
  const rows: ReadinessRow[] = [
    { label: "Метаданные", value: pipeline.metadataPercent, hint: `${counts.metadataReady}/${counts.totalPapers}`, applicable: hasPapers },
    { label: "Аннотации", value: pipeline.abstractPercent, hint: `${counts.withAbstract}/${counts.totalPapers}`, applicable: hasPapers },
    { label: "Полный текст", value: pipeline.fullTextPercent, hint: `${counts.withFullText}/${counts.totalPapers}`, applicable: hasPapers },
    { label: "PDF доступен", value: pipeline.pdfPercent, hint: `${counts.withPdf}/${counts.totalPapers}`, applicable: hasPapers },
    { label: "Контент-блоки", value: pipeline.contentPartsPercent, hint: `${counts.withContentParts}/${counts.totalPapers}`, applicable: hasPapers },
    { label: "Контент готов", value: pipeline.contentReadyPercent, hint: `${counts.contentReady}/${counts.totalPapers}`, applicable: hasPapers },
    { label: "Эмбеддинги в БД", value: pipeline.embeddingPercent, hint: `${counts.withEmbeddings}/${counts.totalPapers}`, applicable: hasPapers },
    {
      label: "Векторный индекс",
      value: pipeline.vectorPercent,
      hint: counts.withEmbeddings > 0 ? `${counts.vectorIndexed}/${counts.withEmbeddings} из эмбеддингов` : "нет кандидатов",
      applicable: counts.withEmbeddings > 0,
      unknown: counts.vectorIdsStatus === "unknown",
    },
    {
      label: "В RAG-индексе",
      value: pipeline.ragPercent,
      hint: counts.ragCandidates > 0 ? `${counts.ragReady}/${counts.ragCandidates} статей-кандидатов` : "нет кандидатов",
      applicable: counts.ragCandidates > 0,
      unknown: counts.ragIdsStatus === "unknown",
    },
    { label: "Qwen-анализ", value: pipeline.qwenPercent, hint: `${counts.qwenReady}/${counts.totalPapers}`, applicable: hasPapers },
  ];

  const recommendations = [
    missing(counts.totalPapers, counts.withFullText) > 0 ? `${missing(counts.totalPapers, counts.withFullText)} документов без полного текста` : null,
    missing(counts.totalPapers, counts.withContentParts) > 0 ? `${missing(counts.totalPapers, counts.withContentParts)} документов без контент-блоков` : null,
    missing(counts.totalPapers, counts.withEmbeddings) > 0 ? `${missing(counts.totalPapers, counts.withEmbeddings)} документов без эмбеддингов` : null,
    counts.vectorIdsStatus === "verified" && Math.max(0, counts.withEmbeddings - counts.vectorIndexed) > 0 ? `${Math.max(0, counts.withEmbeddings - counts.vectorIndexed)} документов с эмбеддингами не подтверждены в векторном индексе` : null,
    counts.ragIdsStatus === "verified" && Math.max(0, counts.ragCandidates - counts.ragReady) > 0 ? `${Math.max(0, counts.ragCandidates - counts.ragReady)} RAG-кандидатов не подтверждены в RAG-индексе` : null,
    counts.vectorIdsStatus === "unknown" ? "проверка векторного индекса сейчас недоступна" : null,
    counts.ragIdsStatus === "unknown" ? "проверка RAG-индекса сейчас недоступна" : null,
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
          <div key={row.label} className={`dashboard-readiness-row${row.applicable === false || row.unknown ? " is-muted" : ""}`}>
            <div className="dashboard-readiness-label">
              <span>{row.label}</span>
              <small>{row.hint}</small>
            </div>
            <div className="dashboard-readiness-track" aria-label={readinessAria(row)}>
              <div style={{ width: `${row.applicable === false || row.unknown ? 0 : clamp(row.value)}%` }} />
            </div>
            <strong>{readinessValue(row)}</strong>
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
