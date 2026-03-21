import { Link } from "react-router-dom";
import { usePatentStore } from "../../store/patentStore";
import type { Patent } from "../../types/patent";

interface PatentTableProps {
  patents: Patent[];
  onSort: (field: keyof Patent) => void;
  sortBy: keyof Patent;
  sortOrder: "asc" | "desc";
  onDeleteOne: (id: number) => void;
}

export default function PatentTable({ patents, onSort, sortBy, sortOrder, onDeleteOne }: PatentTableProps) {
  const selected = usePatentStore((s) => s.selectedIds);
  const toggle = usePatentStore((s) => s.toggleSelect);
  const clear = usePatentStore((s) => s.clearSelection);

  const allChecked = patents.length > 0 && patents.every((p) => selected.includes(p.id));

  const onToggleAll = () => {
    if (allChecked) {
      clear();
      return;
    }
    patents.forEach((p) => {
      if (!selected.includes(p.id)) {
        toggle(p.id);
      }
    });
  };

  return (
    <table className="table">
      <thead>
        <tr>
          <th>
            <input type="checkbox" checked={allChecked} onChange={onToggleAll} />
          </th>
          <th className="sortable" onClick={() => onSort("patentNumber")}>
            № {sortBy === "patentNumber" ? (sortOrder === "asc" ? "↑" : "↓") : ""}
          </th>
          <th className="sortable" onClick={() => onSort("title")}>
            Название {sortBy === "title" ? (sortOrder === "asc" ? "↑" : "↓") : ""}
          </th>
          <th className="sortable" onClick={() => onSort("applicant")}>
            Заявитель {sortBy === "applicant" ? (sortOrder === "asc" ? "↑" : "↓") : ""}
          </th>
          <th className="sortable" onClick={() => onSort("publicationDate")}>
            Дата публикации {sortBy === "publicationDate" ? (sortOrder === "asc" ? "↑" : "↓") : ""}
          </th>
          <th className="sortable" onClick={() => onSort("category")}>
            Категория {sortBy === "category" ? (sortOrder === "asc" ? "↑" : "↓") : ""}
          </th>
          <th className="sortable" onClick={() => onSort("country")}>
            Страна {sortBy === "country" ? (sortOrder === "asc" ? "↑" : "↓") : ""}
          </th>
          <th>Статус</th>
          <th>Действия</th>
        </tr>
      </thead>
      <tbody>
        {patents.map((p) => (
          <tr key={p.id}>
            <td>
              <input type="checkbox" checked={selected.includes(p.id)} onChange={() => toggle(p.id)} />
            </td>
            <td>{p.patentNumber}</td>
            <td>{p.title}</td>
            <td>{p.applicant}</td>
            <td>{p.publicationDate}</td>
            <td>{p.category}</td>
            <td>{p.country}</td>
            <td>
              <span className={`status ${p.status}`}>{p.status === "active" ? "Активен" : "Истек"}</span>
            </td>
            <td className="actions-inline">
              <Link className="action-link" to={`/patents/${p.id}`}>
                Открыть
              </Link>
              <button type="button" onClick={() => alert("Редактирование будет подключено к API")}>
                Ред.
              </button>
              <button type="button" onClick={() => onDeleteOne(p.id)}>
                Удал.
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
