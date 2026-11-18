"use client";
import { Fragment, useState } from "react";
import { CalendarDays } from "lucide-react";
import { Badge, Card, Tabs } from "./ui/primitives";
import { ChartSkeleton, DeltaBadge, QueryError } from "./widgets";
import { DriverTip } from "./driver-tip";
import { useOverview, useWeekGrid } from "@/lib/hooks";
import { fmtDate, fmtInt } from "@/lib/format";
import type { WeekCmp, WeekRow } from "@/lib/types";

const METRICS = [
  { value: "received", label: "Received" }, { value: "edited", label: "Edited" },
  { value: "finalised", label: "Finalised" }, { value: "qc_completed", label: "QC completed" },
] as const;
type MetricKey = (typeof METRICS)[number]["value"];

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (iso: string) => { const [, m, d] = iso.split("-").map(Number); return `${d} ${MON[m - 1]}`; };
const monthName = (iso: string) => { const [y, m] = iso.split("-").map(Number); return `${MON[m - 1]} ${y}`; };

/** A change badge; hover names the project / forms behind it (the very ranges the numbers were counted over). */
function Why({ c, metric, what }: { c: WeekCmp | null; metric: MetricKey; what: string }) {
  if (!c) return <span className="text-xs text-muted-foreground">–</span>;
  const same = c.prev[0] === c.prev[1] ? short(c.prev[0]) : `${short(c.prev[0])} – ${short(c.prev[1])}`;
  const badge = <DeltaBadge change={c} />;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      {c.delta === 0 ? badge : <DriverTip label={`Forms behind the change ${what}`} query={{ metric, cur: c.cur, prev: c.prev }}>{badge}</DriverTip>}
      <span className="text-[11px] text-muted-foreground" title={`${fmtInt(c.previous)} in ${same}`}>was {fmtInt(c.previous)}</span>
    </span>
  );
}

function DayCells({ w, metric, max }: { w: WeekRow; metric: MetricKey; max: number }) {
  return (
    <>
      {w.days.map((d) => {
        if (d.future || d.n == null) return <td key={d.date} className="px-2 py-2 text-right text-muted-foreground" title="Not yet">–</td>;
        const delta = d.n - d.previous;
        const body = (
          <span className={d.n === 0 ? "text-muted-foreground" : "font-medium"}>{fmtInt(d.n)}</span>
        );
        return (
          <td key={d.date} className="px-2 py-2 text-right tabular"
            style={d.n ? { backgroundColor: `rgba(63,196,126,${(0.05 + 0.25 * (d.n / max)).toFixed(3)})` } : undefined}
            title={delta === 0 ? `${d.weekday} ${short(d.date)}: ${fmtInt(d.n)}, same as a week earlier` : undefined}>
            {delta === 0 ? body : (
              <DriverTip label={`Forms behind ${d.weekday} ${short(d.date)}`}
                query={{ metric, cur: [d.date, d.date], prev: [shift(d.date, -7), shift(d.date, -7)] }}>
                {body}
                <span className={`ml-0.5 text-[10px] ${delta > 0 ? "text-good" : "text-bad"}`} aria-label={delta > 0 ? "up on a week earlier" : "down on a week earlier"}>{delta > 0 ? "▲" : "▼"}</span>
              </DriverTip>
            )}
          </td>
        );
      })}
    </>
  );
}

function shift(iso: string, days: number) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/**
 * Every Monday-Sunday week of the selected period, month by month: a cell for each day (empty days are 0, not gaps),
 * each week against the previous week and against the same week of the month before, with the forms behind any difference on hover.
 */
export function WeekGridCard() {
  const [metric, setMetric] = useState<MetricKey>("received");
  const ov = useOverview();
  const q = useWeekGrid(metric);
  const d = q.data;
  const max = Math.max(1, ...(d?.months ?? []).flatMap((m) => m.weeks.flatMap((w) => w.days.map((x) => x.n ?? 0))));

  return (
    <Card className="mt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold"><CalendarDays className="h-4 w-4 text-primary" /> Week by week, Monday to Sunday</h2>
          <p className="max-w-3xl text-xs text-muted-foreground">
            {ov.data ? <>{fmtDate(ov.data.period.from)} – {fmtDate(ov.data.period.to)}. </> : null}
            Week 1, 2, 3… of each month against the same week of the month before, for the client / project selected above.
            Hover a badge or a day to see which project and form caused the rise or the loss.
          </p>
        </div>
        <Tabs label="Measure" value={metric} onChange={setMetric} items={METRICS.map((m) => ({ value: m.value, label: m.label }))} />
      </div>

      {q.isError ? <QueryError error={q.error} /> : q.isLoading || !d ? <ChartSkeleton h={260} /> : d.months.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No complete or running week in this period yet.</p>
      ) : (
        <>
          <p className="mb-2 text-xs text-muted-foreground">{d.rule} ▲▼ = against the same weekday a week earlier.</p>
          <div className="max-h-[40rem] overflow-auto rounded-xl border">
            <table className="w-full min-w-[60rem] text-left text-sm">
              <caption className="sr-only">Weeks from Monday to Sunday with a column for each day</caption>
              <thead className="sticky top-0 z-20 bg-muted/95 backdrop-blur"><tr>
                <th scope="col" className="min-w-[9rem] px-3 py-2 font-medium">Week</th>
                {d.weekdays.map((w) => <th key={w} scope="col" className="px-2 py-2 text-right font-medium">{w}</th>)}
                <th scope="col" className="px-3 py-2 text-right font-medium">Total</th>
                <th scope="col" className="px-3 py-2 text-right font-medium" title="Total divided by the days counted, Sunday included">Per day</th>
                <th scope="col" className="px-3 py-2 font-medium">Same week last month</th>
                <th scope="col" className="px-3 py-2 font-medium">Previous week</th>
              </tr></thead>
              <tbody>
                {d.months.map((m) => (
                  <Fragment key={m.month}>
                    <tr className="border-t bg-card/80">
                      <th scope="row" colSpan={8} className="px-3 py-2 text-left font-semibold">
                        {monthName(m.month)}
                        <span className="ml-2 text-xs font-normal text-muted-foreground">{m.week_count} weeks · {short(m.from)} – {short(m.to)}</span>
                        {m.running && <Badge tone="warn" className="ml-2" title="The last week is still running">running</Badge>}
                      </th>
                      <td className="px-3 py-2 text-right font-semibold tabular">{fmtInt(m.total)}</td>
                      <td />
                      <td className="px-3 py-2"><Why c={m.vs_previous_month} metric={metric} what={`in ${monthName(m.month)} (weeks against the month before)`} /></td>
                      <td />
                    </tr>
                    {m.weeks.map((w) => (
                      <tr key={w.from} className="border-t hover:bg-muted/40">
                        <th scope="row" className="px-3 py-2 text-left font-normal">
                          <span className="font-medium">Week {w.no}</span>
                          {w.running && <Badge tone="warn" className="ml-2" title="Still running: compared with the same number of days of the other week">running</Badge>}
                          <span className="block text-xs text-muted-foreground">{short(w.from)} – {short(w.to)}</span>
                        </th>
                        <DayCells w={w} metric={metric} max={max} />
                        <td className="px-3 py-2 text-right font-semibold tabular">{fmtInt(w.total)}</td>
                        <td className="px-3 py-2 text-right tabular text-muted-foreground">{w.avg_per_day.toLocaleString("en-US", { maximumFractionDigits: 1 })}</td>
                        <td className="px-3 py-2">
                          {w.same_week_last_month_missing
                            ? <span className="text-xs text-muted-foreground" title="The month before had fewer weeks">no week {w.no} last month</span>
                            : <Why c={w.vs_same_week_last_month} metric={metric} what={`of week ${w.no} against week ${w.no} of the month before`} />}
                        </td>
                        <td className="px-3 py-2"><Why c={w.vs_previous_week} metric={metric} what="against the week before" /></td>
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
              <tfoot className="sticky bottom-0 bg-muted/95 backdrop-blur"><tr className="border-t font-semibold">
                <th scope="row" colSpan={8} className="px-3 py-2 text-left">All weeks shown</th>
                <td className="px-3 py-2 text-right tabular">{fmtInt(d.total)}</td><td colSpan={3} />
              </tr></tfoot>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
