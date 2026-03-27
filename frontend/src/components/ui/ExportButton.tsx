import { useState } from "react";
import type { Paper } from "../../types/paper";

interface ExportButtonProps {
  papers: Paper[];
  filename?: string;
  variant?: "csv" | "excel";
  className?: string;
}

/**
 * Компонент кнопки экспорта статей в CSV/Excel.
 */
export default function ExportButton({
  papers,
  filename = "papers_export",
  variant = "csv",
  className = "",
}: ExportButtonProps) {
  const [exporting, setExporting] = useState(false);

  const convertToCSV = (data: Paper[]): string => {
    if (!data || data.length === 0) return "";

    const headers = [
      "ID",
      "Title",
      "Authors",
      "Publication Date",
      "Journal",
      "DOI",
      "Source",
      "Abstract",
      "Keywords",
      "URL",
    ];

    const rows = data.map((paper) => [
      paper.id,
      escapeCsv(paper.title),
      escapeCsv(Array.isArray(paper.authors) ? paper.authors.join("; ") : ""),
      paper.publicationDate ? paper.publicationDate.slice(0, 10) : "",
      escapeCsv(paper.journal || ""),
      escapeCsv(paper.doi || ""),
      paper.source,
      escapeCsv(paper.abstract || ""),
      escapeCsv(Array.isArray(paper.keywords) ? paper.keywords.join("; ") : ""),
      paper.url || "",
    ]);

    return [headers.join(","), ...rows.map((row) => row.join(","))].join("\n");
  };

  const escapeCsv = (text: string): string => {
    if (!text) return '""';
    // Экранирование кавычек и обработка запятых
    const escaped = text.replace(/"/g, '""');
    if (escaped.includes(",") || escaped.includes("\n") || escaped.includes('"')) {
      return `"${escaped}"`;
    }
    return escaped;
  };

  const convertToExcel = async (data: Paper[]): Promise<Blob> => {
    // Простая реализация через CSV с BOM для Excel
    const csv = convertToCSV(data);
    // Добавляем BOM для корректного отображения в Excel
    const BOM = "\uFEFF";
    return new Blob([BOM + csv], {
      type: "application/vnd.ms-excel;charset=utf-8",
    });
  };

  const handleExport = async () => {
    if (!papers || papers.length === 0) {
      alert("Нет данных для экспорта");
      return;
    }

    setExporting(true);

    try {
      let blob: Blob;
      let fileExtension: string;

      if (variant === "excel") {
        blob = await convertToExcel(papers);
        fileExtension = "xls";
      } else {
        const csv = convertToCSV(papers);
        blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
        fileExtension = "csv";
      }

      // Создаем ссылку для скачивания
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${filename}.${fileExtension}`;
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Export error:", error);
      alert("Ошибка при экспорте");
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      {variant === "csv" ? (
        <button
          className={`btn ${className}`}
          onClick={handleExport}
          disabled={exporting || papers.length === 0}
          title="Экспорт в CSV"
        >
          {exporting ? "Экспорт..." : "📄 CSV"}
        </button>
      ) : (
        <button
          className={`btn ${className}`}
          onClick={handleExport}
          disabled={exporting || papers.length === 0}
          title="Экспорт в Excel"
        >
          {exporting ? "Экспорт..." : "📊 Excel"}
        </button>
      )}
    </>
  );
}

/**
 * Компонент группы кнопок экспорта (CSV + Excel).
 */
export function ExportButtons({
  papers,
  filename,
  className = "",
}: {
  papers: Paper[];
  filename?: string;
  className?: string;
}) {
  return (
    <div className={`export-buttons ${className}`} style={{ display: "flex", gap: 8 }}>
      <ExportButton papers={papers} filename={filename} variant="csv" />
      <ExportButton papers={papers} filename={filename} variant="excel" />
    </div>
  );
}
