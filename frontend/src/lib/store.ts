"use client";
import { create } from "zustand";
import { Filters, withPeriodPatch } from "./filters";

interface FilterState {
  filters: Filters;
  /** Merge a patch; period fields clear conflicting period fields. Undefined removes a key. */
  patch: (p: Partial<Filters>) => void;
  replace: (f: Filters) => void;
  reset: () => void;
}

export const useFilterStore = create<FilterState>((set) => ({
  filters: {},
  patch: (p) => set((s) => ({ filters: withPeriodPatch(s.filters, p) })),
  replace: (f) => set({ filters: f }),
  reset: () => set({ filters: {} }),
}));
