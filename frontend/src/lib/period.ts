import type { Period } from "./types";

export const GRANULARITIES = ["day", "week", "month", "quarter", "year"] as const;
export type Granularity = (typeof GRANULARITIES)[number];

/** A readable default bucket size for the selected range. */
export function autoGranularity(p?: Period): Granularity {
  if (!p) return "day";
  const days = (new Date(p.to).getTime() - new Date(p.from).getTime()) / 86_400_000 + 1;
  if (days <= 35) return "day";
  if (days <= 140) return "week";
  if (days <= 900) return "month";
  return "quarter";
}

export const GRAN_LABEL: Record<Granularity, string> = {
  day: "Daily", week: "Weekly", month: "Monthly", quarter: "Quarterly", year: "Yearly",
};
