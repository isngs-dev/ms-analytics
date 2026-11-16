"use client";
import { create } from "zustand";
import type { MetricKey } from "./types";

interface DrillState {
  open: boolean;
  metric?: MetricKey;
  title: string;
  extra: Record<string, string | number | undefined>; // e.g. a project_id picked on a chart
  show: (d: { metric?: MetricKey; title: string; extra?: DrillState["extra"] }) => void;
  close: () => void;
}

export const useDrill = create<DrillState>((set) => ({
  open: false, title: "", extra: {},
  show: ({ metric, title, extra }) => set({ open: true, metric, title, extra: extra ?? {} }),
  close: () => set({ open: false }),
}));
