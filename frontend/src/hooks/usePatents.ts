import { useMemo } from "react";
import { usePatentStore } from "../store/patentStore";
import { useFilterStore } from "../store/filterStore";

export function usePatents() {
  const patents = usePatentStore((s) => s.patents);
  const filters = useFilterStore((s) => s.filters);

  const filtered = useMemo(() => {
    return patents.filter((p) => {
      const bySearch =
        !filters.search ||
        p.title.toLowerCase().includes(filters.search.toLowerCase()) ||
        p.patentNumber.toLowerCase().includes(filters.search.toLowerCase());
      const byCategory = !filters.category || p.category === filters.category;
      const byCountry = !filters.country || p.country === filters.country;
      const byStatus = !filters.status || p.status === filters.status;
      const byDateFrom = !filters.dateFrom || p.publicationDate >= filters.dateFrom;
      const byDateTo = !filters.dateTo || p.publicationDate <= filters.dateTo;
      return bySearch && byCategory && byCountry && byStatus && byDateFrom && byDateTo;
    });
  }, [patents, filters]);

  return { patents: filtered, allPatents: patents };
}
