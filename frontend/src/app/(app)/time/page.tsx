"use client";
import { useState } from "react";
import { Flag } from "lucide-react";
import { Badge, Card, Select, Tabs } from "@/components/ui/primitives";
import type { Filters } from "@/lib/filters";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ChartCard, ChartSkeleton, DeltaBadge, PageHeader, QueryError } from "@/components/widgets";
import { TrendChart } from "@/components/charts";
import { DriverTip } from "@/components/driver-tip";
import { useCompare, useOverview, useTimeseries } from "@/lib/hooks";
import { useFilterStore } from "@/lib/store";
import { fmtDate, fmtInt } from "@/lib/format";
import { autoGranularity, GRANULARITIES, GRAN_LABEL, Granularity } from "@/lib/period";
import type { Change } from "@/lib/types";

/** The comparison follows the global period filter: the selected period against the one before it. */
function previousPeriodMode(f: Filters): { mode: string; level: string } {
  if (f.date_from || f.date_to) return { mode: "custom", level: "date range" };
  if (f.week) return { mode: "week_vs_prev_week", level: "week" };
  if (f.month) return { mode: "month_vs_prev_month", level: "month" };
  if (f.quarter) return { mode: "quarter_vs_prev_quarter", level: "quarter" };
  if (f.year) return { mode: "year_vs_prev_year", level: "year" };
  return { mode: "custom", level: "period" };
}
const COMPARE_WITH = [
  { value: "prev", label: "Previous period" },
  { value: "yoy", label: "Same period last year" },
  { value: "week_vs_prev_month_week", label: "Same week last month (week filter only)" },
];
type CmpGran = "week" | "month" | "quarter" | "year";
const CMP_GRANS: { value: CmpGran; label: string }[] = [
  { value: "week", label: "Weekly" }, { value: "month", label: "Monthly" },
  { value: "quarter", label: "Quarterly" }, { value: "year", label: "Yearly" },
];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const utc = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number) => new Date(d.getTime() + n * 86_400_000);

/** First/last day and a readable label of a calendar bucket. */
function bucketInfo(start: string, g: CmpGran): { label: string; sub?: string; end: string } {
  const s = utc(start), y = s.getUTCFullYear(), m = s.getUTCMonth();
  if (g === "year") return { label: String(y), end: `${y}-12-31` };
  if (g === "quarter") return { label: `Q${Math.floor(m / 3) + 1} ${y}`, sub: `${MON[m]} – ${MON[m + 2]}`, end: iso(new Date(Date.UTC(y, m + 3, 0))) };
  if (g === "month") return { label: `${MON[m]} ${y}`, end: iso(new Date(Date.UTC(y, m + 1, 0))) };
  const e = addDays(s, 6);
  return { label: `${s.getUTCDate()} ${MON[m]} ${y}`, sub: `to ${e.getUTCDate()} ${MON[e.getUTCMonth()]}`, end: iso(e) };
}

type Range = [string, string];
/** A change badge that, on hover, names the forms behind the difference (same periods and filters as the numbers). */
function WhyBadge({ change, less, metric, cur, prev, projectId }: {
  change: Change; less?: boolean; metric: string; cur: Range; prev: Range; projectId?: number;
}) {
  const badge = <DeltaBadge change={change} goodWhenDown={less} />;
  if (change.delta === 0) return badge;
  return <DriverTip label={`Forms behind this change in ${metric.replace(/_/g, " ")}`} query={{ metric, cur, prev, projectId }}>{badge}</DriverTip>;
}

function stepChange(cur: number, prev: number): Change {
  const pct = prev === 0 ? null : Math.round((1000 * (cur - prev)) / prev) / 10;
  return { current: cur, previous: prev, delta: cur - prev, pct_change: pct, direction: cur === prev ? "flat" : cur > prev ? "up" : "down" };
}

const STEP_COLS: { key: "received" | "edited" | "finalised" | "qc_completed"; label: string; less?: boolean }[] = [
  { key: "received", label: "Received" }, { key: "edited", label: "Edited" }, { key: "finalised", label: "Finalised" },
  { key: "qc_completed", label: "QC completed" },
];

/** A bucket limited to the selected range, because the table counts only what lies inside it. */
const clip = (from: string, to: string, period?: { from: string; to: string }): Range =>
  [period && from < period.from ? period.from : from, period && to > period.to ? period.to : to];

/** Every week / month / quarter / year inside the selected range, each compared with the bucket before it. */
function PeriodByPeriod({ period }: { period?: { from: string; to: string } }) {
  const auto = autoGranularity(period);
  const [pick, setPick] = useState<CmpGran | null>(null);
  const g: CmpGran = pick ?? (auto === "day" ? "week" : auto);
  const ts = useTimeseries(g);
  const pts = ts.data?.points ?? [];
  const rows = pts.map((p, i) => {
    const info = bucketInfo(p.bucket, g);
    const partial = !!period && (p.bucket < period.from || info.end > period.to);
    return { p, info, partial, prev: i > 0 ? pts[i - 1] : null };
  });
  const total = (k: (typeof STEP_COLS)[number]["key"]) => pts.reduce((a, p) => a + p[k], 0);
  return (
    <ChartCard className="mt-4" title="Period-by-period comparison"
      subtitle={`Each ${g} in the selected range against the ${g} before it`}
      action={<Tabs label="Comparison basis" value={g} onChange={setPick} items={CMP_GRANS} />}>
      {ts.isError ? <QueryError error={ts.error} /> : ts.isLoading ? <ChartSkeleton h={200} /> : (
        <div className="max-h-[32rem] overflow-auto rounded-xl border">
          <table className="w-full min-w-[46rem] text-left text-sm">
            <caption className="sr-only">Comparison of each {g} with the previous {g}</caption>
            <thead className="sticky top-0 z-10 bg-muted/90 backdrop-blur"><tr>
              <th scope="col" className="px-3 py-2 font-medium">{CMP_GRANS.find((x) => x.value === g)!.label.replace("ly", "")}</th>
              {STEP_COLS.map((c) => <th key={c.key} scope="col" className="px-3 py-2 font-medium">{c.label}</th>)}
            </tr></thead>
            <tbody>
              {rows.map(({ p, info, partial, prev }) => (
                <tr key={p.bucket} className="border-t hover:bg-muted/40">
                  <th scope="row" className="px-3 py-2 text-left font-medium">
                    {info.label} {partial && <Badge tone="warn" title="Only part of this period lies inside the selected range, so its change is not like-for-like">partial</Badge>}
                    {info.sub && <span className="block text-xs font-normal text-muted-foreground">{info.sub}</span>}
                  </th>
                  {STEP_COLS.map((c) => (
                    <td key={c.key} className="px-3 py-2">
                      <span className="tabular">{fmtInt(p[c.key])}</span>{" "}
                      {prev ? <WhyBadge change={stepChange(p[c.key], prev[c.key])} less={c.less} metric={c.key}
                        cur={clip(p.bucket, info.end, period)} prev={clip(prev.bucket, bucketInfo(prev.bucket, g).end, period)} />
                        : <span className="text-xs text-muted-foreground">–</span>}
                    </td>
                  ))}
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">No data in this range</td></tr>}
            </tbody>
            {rows.length > 0 && (
              <tfoot className="sticky bottom-0 bg-muted/90 backdrop-blur"><tr className="border-t font-semibold">
                <th scope="row" className="px-3 py-2 text-left">Total</th>
                {STEP_COLS.map((c) => <td key={c.key} className="px-3 py-2 tabular">{fmtInt(total(c.key))}</td>)}
              </tr></tfoot>
            )}
          </table>
        </div>
      )}
    </ChartCard>
  );
}

const FLAG: Record<string, string> = { volume_drop: "Volume drop", pending_growth: "Pending growing" };
const METRICS: { key: string; label: string; lessIsBetter?: boolean }[] = [
  { key: "received", label: "Received" }, { key: "edited", label: "Edited" }, { key: "qc_completed", label: "QC completed" },
  { key: "pending_editing", label: "Pending editing", lessIsBetter: true }, { key: "qc_pending", label: "QC pending", lessIsBetter: true },
];

export default function TimePage() {
  const ov = useOverview();
  const [gran, setGran] = useState<Granularity | null>(null);
  const g = gran ?? autoGranularity(ov.data?.period);
  const ts = useTimeseries(g);
  const filters = useFilterStore((s) => s.filters);
  const [against, setAgainst] = useState("prev");
  const base = previousPeriodMode(filters);
  const mode = against === "yoy" ? "yoy"
    : against === "week_vs_prev_month_week" && filters.week && !filters.date_from && !filters.date_to ? "week_vs_prev_month_week"
    : base.mode;
  // anchored on the start of the selected period (the API resolves the filters to a date range first)
  const cmp = useCompare(mode, ov.data?.period.from, !!ov.data);
  const patch = useFilterStore((s) => s.patch);
  const c = cmp.data;

  return (
    <>
      <PageHeader title="Time analytics & comparisons" subtitle="Everything here follows the filters above: trend, period-over-period change and early-warning flags">
        <Breadcrumbs />
      </PageHeader>

      <ChartCard title="Trend" subtitle={ov.data ? `${fmtDate(ov.data.period.from)} – ${fmtDate(ov.data.period.to)}` : undefined}
        action={<Tabs label="Granularity" value={g} onChange={setGran} items={GRANULARITIES.map((x) => ({ value: x, label: GRAN_LABEL[x] }))} />}>
        {ts.isLoading ? <ChartSkeleton /> : ts.isError ? <QueryError error={ts.error} /> : (
          <TrendChart points={ts.data!.points} granularity={g} keys={["received", "edited", "finalised", "qc_completed"]} height={340} />
        )}
      </ChartCard>

      <PeriodByPeriod period={ov.data?.period} />

      <Card className="mt-4">
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <Select label={`Compare selected ${base.level} with`} className="w-80" value={against}
            onChange={(v) => setAgainst(v || "prev")} placeholder="Choose"
            options={COMPARE_WITH.filter((o) => o.value !== "week_vs_prev_month_week" || (filters.week && !filters.date_from && !filters.date_to))} />
          {c?.partial && <Badge tone="warn" title="The current period is unfinished, so only the same number of days of the previous period are compared">to date</Badge>}
          {c && <p className="ml-auto text-sm text-muted-foreground">{fmtDate(c.current.from)} – {fmtDate(c.current.to)} <span className="mx-1">vs</span> {fmtDate(c.previous.from)} – {fmtDate(c.previous.to)}</p>}
        </div>
        {cmp.isError && <QueryError error={cmp.error} />}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {METRICS.map((m) => {
            const ch: Change | undefined = c?.overall[m.key];
            return (
              <div key={m.key} className="rounded-xl border bg-card/50 p-3">
                <p className="text-xs uppercase tracking-wider text-muted-foreground">{m.label}</p>
                <p className="mt-1 text-2xl font-semibold tabular">{ch ? fmtInt(ch.current) : "–"}</p>
                <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                  {ch && c && <WhyBadge change={ch} less={m.lessIsBetter} metric={m.key} cur={[c.current.from, c.current.to]} prev={[c.previous.from, c.previous.to]} />} {ch && <span>was {fmtInt(ch.previous)}</span>}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <Card className="mt-4">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold"><Flag className="h-4 w-4 text-warn" /> Projects to watch</h2>
        <p className="mb-3 text-xs text-muted-foreground">Flagged when incoming volume drops ≥15%, pending editing grows ≥25% (and ≥10 forms).</p>
        <div className="overflow-auto rounded-xl border">
          <table className="w-full min-w-[52rem] text-left text-sm">
            <caption className="sr-only">Project comparison</caption>
            <thead className="bg-muted/80"><tr>
              <th scope="col" className="px-3 py-2 font-medium">Project</th>
              {["Received", "Edited", "QC done", "Pending"].map((h) => <th key={h} scope="col" className="px-3 py-2 font-medium">{h}</th>)}
              <th scope="col" className="px-3 py-2 font-medium">Flags</th>
            </tr></thead>
            <tbody>
              {(c?.projects ?? []).map((p) => (
                <tr key={p.project_id} className="border-t hover:bg-muted/40">
                  <th scope="row" className="px-3 py-2 text-left font-medium">
                    <button className="text-primary hover:underline" onClick={() => patch({ project_id: p.project_id })}>{p.project}</button>
                    <span className="block text-xs font-normal text-muted-foreground">{p.client}</span>
                  </th>
                  {([["received", false], ["edited", false], ["qc_completed", false], ["pending_editing", true]] as const).map(([k, less]) => (
                    <td key={k} className="px-3 py-2">
                      <span className="tabular">{fmtInt(p[k].current)}</span>{" "}
                      {c && <WhyBadge change={p[k]} less={less} metric={k} projectId={p.project_id} cur={[c.current.from, c.current.to]} prev={[c.previous.from, c.previous.to]} />}
                    </td>
                  ))}
                  <td className="px-3 py-2"><div className="flex flex-wrap gap-1">{p.flags.map((f) => <Badge key={f} tone="bad">{FLAG[f] ?? f}</Badge>)}</div></td>
                </tr>
              ))}
              {cmp.isLoading && <tr><td colSpan={6} className="px-3 py-10 text-center text-muted-foreground">Loading…</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
