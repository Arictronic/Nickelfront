import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PatentFilters from "../components/patents/PatentFilters";
import PatentTable from "../components/patents/PatentTable";
import Pagination from "../components/ui/Pagination";
import { usePatentStore } from "../store/patentStore";
import { usePatents } from "../hooks/usePatents";
import { useFilters } from "../hooks/useFilters";
import type { Patent } from "../types/patent";

export default function Patents() {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<keyof Patent>("publicationDate");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const pageSize = 6;

  const { patents } = usePatents();
  const { filters, setFilter } = useFilters();
  const selected = usePatentStore((s) => s.selectedIds);
  const storePatents = usePatentStore((s) => s.patents);
  const setPatents = usePatentStore((s) => s.setPatents);
  const removeSelected = usePatentStore((s) => s.removeSelected);

  useEffect(() => {
    setFilter("search", params.get("search") ?? "");
    setFilter("category", params.get("category") ?? "");
    setFilter("country", params.get("country") ?? "");
    setFilter("status", (params.get("status") as "" | "active" | "expired") ?? "");
    setFilter("dateFrom", params.get("dateFrom") ?? "");
    setFilter("dateTo", params.get("dateTo") ?? "");
    const pageParam = Number(params.get("page") ?? "1");
    setPage(Number.isNaN(pageParam) ? 1 : Math.max(1, pageParam));
    // run once on load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const next = new URLSearchParams();
    if (filters.search) next.set("search", filters.search);
    if (filters.category) next.set("category", filters.category);
    if (filters.country) next.set("country", filters.country);
    if (filters.status) next.set("status", filters.status);
    if (filters.dateFrom) next.set("dateFrom", filters.dateFrom);
    if (filters.dateTo) next.set("dateTo", filters.dateTo);
    next.set("page", String(page));
    setParams(next, { replace: true });
  }, [filters, page, setParams]);

  const sortedPatents = useMemo(() => {
    const copy = [...patents];
    copy.sort((a, b) => {
      const left = String(a[sortBy]).toLowerCase();
      const right = String(b[sortBy]).toLowerCase();
      return sortOrder === "asc" ? left.localeCompare(right) : right.localeCompare(left);
    });
    return copy;
  }, [patents, sortBy, sortOrder]);

  const totalPages = Math.max(1, Math.ceil(sortedPatents.length / pageSize));
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  const paginated = useMemo(() => {
    const from = (page - 1) * pageSize;
    return sortedPatents.slice(from, from + pageSize);
  }, [page, sortedPatents]);

  const handleSort = (field: keyof Patent) => {
    if (sortBy === field) {
      setSortOrder((v) => (v === "asc" ? "desc" : "asc"));
      return;
    }
    setSortBy(field);
    setSortOrder("asc");
  };

  const exportCSV = () => {
    if (selected.length === 0) {
      alert("Выберите хотя бы один патент");
      return;
    }
    const rows = storePatents.filter((p) => selected.includes(p.id));
    const csv = [
      "patentNumber,title,applicant,publicationDate,category,country,status",
      ...rows.map((p) =>
        [p.patentNumber, p.title, p.applicant, p.publicationDate, p.category, p.country, p.status]
          .map((x) => `"${String(x).replaceAll('"', '""')}"`)
          .join(",")
      ),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "patents.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportExcelMock = () => {
    alert("Excel экспорт временно работает как CSV (mock)");
    exportCSV();
  };

  const deleteOne = (id: number) => {
    if (!window.confirm("Удалить выбранный патент?")) return;
    setPatents(storePatents.filter((p) => p.id !== id));
  };

  const deleteSelected = () => {
    if (selected.length === 0) return;
    if (!window.confirm(`Удалить ${selected.length} элементов?`)) return;
    removeSelected();
  };

  return (
    <div className="page">
      <div className="page-head">
        <h2>Патенты</h2>
        <div className="counter-badge">Всего после фильтрации: {sortedPatents.length}</div>
      </div>
      <PatentFilters />
      <div className="actions">
        <button className="btn btn-primary" onClick={exportCSV}>
          Экспорт CSV
        </button>
        <button className="btn" onClick={exportExcelMock}>
          Экспорт Excel
        </button>
        <button className="btn btn-danger" onClick={deleteSelected}>
          Удалить выбранные
        </button>
      </div>
      <PatentTable patents={paginated} onSort={handleSort} sortBy={sortBy} sortOrder={sortOrder} onDeleteOne={deleteOne} />
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </div>
  );
}
