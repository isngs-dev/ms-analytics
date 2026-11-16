/** Global filters: the shape, URL (de)serialisation and API-param mapping. */

export interface Filters {
  /** "all" = every year in the data (replaces the whole period chain). */
  range?: "all";
  year?: number;
  quarter?: number;
  month?: number;
  week?: number;
  date_from?: string;
  date_to?: string;
  client_id?: number;
  project_id?: number;
  editor_id?: number;
  edit_status?: string;
  qc_status?: string;
  editor_type?: string;
}

export const FILTER_KEYS = [
  "range", "year", "quarter", "month", "week", "date_from", "date_to", "client_id", "project_id", "editor_id",
  "edit_status", "qc_status", "editor_type",
] as const satisfies readonly (keyof Filters)[];

const NUMERIC = new Set<string>(["year", "quarter", "month", "week", "client_id", "project_id", "editor_id"]);

export function parseFilters(sp: URLSearchParams): Filters {
  const f: Record<string, string | number> = {};
  for (const k of FILTER_KEYS) {
    const v = sp.get(k);
    if (v == null || v === "") continue;
    if (NUMERIC.has(k)) {
      const n = Number(v);
      if (Number.isFinite(n)) f[k] = n;
    } else if (k === "range") {
      if (v === "all") f[k] = v;
    } else f[k] = v;
  }
  return f as Filters;
}

/** Stable string (keys in fixed order) so equality checks never loop. */
export function serializeFilters(f: Filters): string {
  const sp = new URLSearchParams();
  for (const k of FILTER_KEYS) {
    const v = f[k];
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  return sp.toString();
}

/** Query params for the API (it accepts the same names; client/project ids are lists server-side). */
export function toApiParams(f: Filters): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const k of FILTER_KEYS) {
    const v = f[k];
    if (v !== undefined && v !== null && v !== "") out[k] = v;
  }
  return out;
}

export const PERIOD_KEYS = ["year", "quarter", "month", "week", "date_from", "date_to"] as const;

/** Calendar quarters: Q1 Jan-Mar, Q2 Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec. */
export const quarterOfMonth = (m: number) => Math.ceil(m / 3);
export const monthsOfQuarter = (q: number) => [1, 2, 3].map((i) => 3 * (q - 1) + i);

/**
 * The period filters are nested: Year > Quarter > Month > Week. Choosing a level clears everything below it
 * (a different quarter means a different set of months), picking a month fixes its quarter, and clearing a level
 * clears the levels beneath. A custom date range replaces the whole chain.
 */
export function withPeriodPatch(f: Filters, patch: Partial<Filters>): Filters {
  const next: Filters = { ...f, ...patch };
  const touched = Object.keys(patch);
  if (patch.range === "all") {
    for (const k of PERIOD_KEYS) delete next[k];
  } else if (touched.includes("date_from") || touched.includes("date_to")) {
    delete next.range;
    delete next.year; delete next.quarter; delete next.month; delete next.week;
  } else if (touched.some((k) => ["year", "quarter", "month", "week"].includes(k))) {
    delete next.range;
    delete next.date_from; delete next.date_to;
    if ("year" in patch) {
      delete next.week; // ISO weeks belong to one year
      if (!patch.year) { delete next.quarter; delete next.month; }
    }
    if ("quarter" in patch) {
      delete next.month; delete next.week;
    }
    if ("month" in patch) {
      delete next.week;
      if (patch.month) next.quarter = quarterOfMonth(patch.month);
    }
  }
  for (const k of Object.keys(next) as (keyof Filters)[]) if (next[k] === undefined) delete next[k];
  return next;
}

/** ISO week number and ISO year of a date (Monday-based, week 1 contains the first Thursday). */
export function isoWeek(d: Date): { week: number; year: number } {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const year = t.getUTCFullYear();
  const week = Math.ceil(((t.getTime() - Date.UTC(year, 0, 1)) / 86_400_000 + 1) / 7);
  return { week, year };
}

/** ISO weeks (of `year`) that overlap the selected period, with their Monday-Sunday labels. */
export function weeksInPeriod(year: number, quarter?: number, month?: number): { week: number; label: string }[] {
  const start = month ? new Date(year, month - 1, 1) : quarter ? new Date(year, 3 * (quarter - 1), 1) : new Date(year, 0, 1);
  const end = month ? new Date(year, month, 0) : quarter ? new Date(year, 3 * quarter, 0) : new Date(year, 11, 31);
  const seen = new Map<number, Date>();
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const iso = isoWeek(d);
    if (iso.year !== year || seen.has(iso.week)) continue;
    const monday = new Date(d);
    monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    seen.set(iso.week, monday);
  }
  const fmt = (x: Date) => x.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return [...seen.entries()].map(([week, mon]) => {
    const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
    return { week, label: `W${week} · ${fmt(mon)} – ${fmt(sun)}` };
  });
}
