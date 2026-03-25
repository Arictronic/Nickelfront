import { useFilterStore } from "../store/filterStore";

export function useFilters() {
  const filters = useFilterStore((s) => s.filters);
  const setFilter = useFilterStore((s) => s.setFilter);
  const resetFilters = useFilterStore((s) => s.resetFilters);
  return { filters, setFilter, resetFilters };
}
