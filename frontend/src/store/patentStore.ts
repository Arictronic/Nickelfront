import { create } from "zustand";
import type { Patent } from "../types/patent";
import { mockPatents } from "../utils/mockData";

interface PatentState {
  patents: Patent[];
  selectedIds: number[];
  setPatents: (patents: Patent[]) => void;
  toggleSelect: (id: number) => void;
  clearSelection: () => void;
  removeSelected: () => void;
}

export const usePatentStore = create<PatentState>((set) => ({
  patents: mockPatents,
  selectedIds: [],
  setPatents: (patents) => set({ patents }),
  toggleSelect: (id) =>
    set((s) => ({
      selectedIds: s.selectedIds.includes(id)
        ? s.selectedIds.filter((x) => x !== id)
        : [...s.selectedIds, id],
    })),
  clearSelection: () => set({ selectedIds: [] }),
  removeSelected: () =>
    set((s) => ({
      patents: s.patents.filter((p) => !s.selectedIds.includes(p.id)),
      selectedIds: [],
    })),
}));
