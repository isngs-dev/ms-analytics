import type { Filters } from "./filters";
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

/**
 * The bucket sizes that make sense for what is selected: a day shows only days, a week days and weeks,
 * a month days / weeks / months, a quarter up to quarters, and a year (or nothing picked) all five.
 * A from–to range is judged by its length.
 */
export function allowedGranularities(f: Filters, p?: Period): Granularity[] {
  let top: number;
  if (f.date_from || f.date_to) {
    const from = f.date_from ?? f.date_to!, to = f.date_to ?? f.date_from!;
    top = spanTop((new Date(to).getTime() - new Date(from).getTime()) / 86_400_000 + 1);
  } else if (f.week) top = 1;
  else if (f.month) top = 2;
  else if (f.quarter) top = 3;
  else if (f.year) top = 4;
  else top = p ? spanTop((new Date(p.to).getTime() - new Date(p.from).getTime()) / 86_400_000 + 1) : 4;
  return GRANULARITIES.slice(0, top + 1);
}

// day <7 days → day only; a week → +week; a month (28+) → +month; a quarter (89+) → +quarter; a year (360+) → +year
const spanTop = (days: number) => (days < 7 ? 0 : days < 28 ? 1 : days < 89 ? 2 : days < 360 ? 3 : 4);

/** The bucket size to draw: the user's pick, else the automatic one, always kept inside what is allowed. */
export function effectiveGranularity(picked: Granularity | null, auto: Granularity, allowed: Granularity[]): Granularity {
  const g = picked ?? auto;
  if (allowed.includes(g)) return g;
  return allowed[allowed.length - 1];
}
