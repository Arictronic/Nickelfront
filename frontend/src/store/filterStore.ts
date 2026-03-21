import { create } from "zustand";
import type { PatentFilters } from "../types/patent";

const defaultFilters: PatentFilters = {
  search: "",
  category: "",
  country: "",
  status: "",
  dateFrom: "",
  dateTo: "",
};

interface FilterState {
  filters: PatentFilters;
  setFilter: <K extends keyof PatentFilters>(key: K, value: PatentFilters[K]) => void;
  resetFilters: () => void;
}

export const useFilterStore = create<FilterState>((set) => ({
  filters: defaultFilters,
  setFilter: (key, value) => set((s) => ({ filters: { ...s.filters, [key]: value } })),
  resetFilters: () => set({ filters: defaultFilters }),
}));
