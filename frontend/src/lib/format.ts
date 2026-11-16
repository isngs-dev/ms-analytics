const nf = new Intl.NumberFormat("en-US");
export const fmtInt = (n: number | null | undefined) => (n == null ? "–" : nf.format(Math.round(n)));
export const fmtPct = (n: number | null | undefined, digits = 1) =>
  n == null ? "–" : `${n.toFixed(digits)}%`;

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "–";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** Compact label for a chart bucket start date. */
export function fmtBucket(iso: string, g: string) {
  const d = new Date(`${iso}T00:00:00`);
  if (g === "year") return String(d.getFullYear());
  if (g === "quarter") return `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}`;
  if (g === "month") return d.toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const label = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
