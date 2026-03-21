import { useFilters } from "../../hooks/useFilters";
import SearchBar from "./SearchBar";
import { usePatentStore } from "../../store/patentStore";

export default function PatentFilters() {
  const { filters, setFilter, resetFilters } = useFilters();
  const patents = usePatentStore((s) => s.patents);
  const categories = Array.from(new Set(patents.map((p) => p.category))).sort();
  const countries = Array.from(new Set(patents.map((p) => p.country))).sort();

  return (
    <div className="filters">
      <SearchBar value={filters.search} onChange={(v) => setFilter("search", v)} />
      <select value={filters.category} onChange={(e) => setFilter("category", e.target.value)}>
        <option value="">Все категории</option>
        {categories.map((category) => (
          <option key={category} value={category}>
            {category}
          </option>
        ))}
      </select>
      <select value={filters.country} onChange={(e) => setFilter("country", e.target.value)}>
        <option value="">Все страны</option>
        {countries.map((country) => (
          <option key={country} value={country}>
            {country}
          </option>
        ))}
      </select>
      <input type="date" value={filters.dateFrom} onChange={(e) => setFilter("dateFrom", e.target.value)} />
      <input type="date" value={filters.dateTo} onChange={(e) => setFilter("dateTo", e.target.value)} />
      <select value={filters.status} onChange={(e) => setFilter("status", e.target.value as "active" | "expired" | "")}>
        <option value="">Все статусы</option>
        <option value="active">Активен</option>
        <option value="expired">Истек</option>
      </select>
      <button className="btn" onClick={resetFilters}>
        Сбросить
      </button>
    </div>
  );
}
