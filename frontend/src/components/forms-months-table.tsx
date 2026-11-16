"use client";
import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Input, Tabs } from "./ui/primitives";
import { ChartSkeleton, QueryError } from "./widgets";
import { DriverTip, tipFromRows, type TipData } from "./driver-tip";
import { useFormsMonths } from "@/lib/hooks";
import { useFilterStore } from "@/lib/store";
import { fmtInt } from "@/lib/format";
import type { DriverRow } from "@/lib/types";

const METRICS = [
  { value: "received", label: "Forms received" },
  { value: "edited", label: "Edited" },
  { value: "qc_completed", label: "QC completed" },
] as const;
type MetricKey = (typeof METRICS)[number]["value"];

const monthLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
const signed = (n: number) => (n > 0 ? `+${fmtInt(n)}` : n < 0 ? `−${fmtInt(-n)}` : "0");

/** One number per month; the arrow shows the move against the month before, the tint the size within the row. */
function MonthCells({ values, partial, strong = false, why, months }: {
  values: number[]; partial: number; strong?: boolean; months?: string[];
  /** forms (name + their own monthly values) behind this row, to explain a month's change on hover */
  why?: { name: string; project: string; id: number; months: number[] }[];
}) {
  const max = Math.max(1, ...values);
  return (
    <>
      {values.map((n, i) => {
        const prev = i > 0 ? values[i - 1] : null;
        const delta = prev == null ? 0 : n - prev;
        // the running month is not a full month: never colour it as a fall
        const arrow = prev == null || delta === 0 || i === partial ? null : delta > 0 ? "up" : "down";
        const shown = (
          <>
            {n ? fmtInt(n) : <span className="text-muted-foreground">·</span>}
            {arrow && <span aria-label={arrow === "up" ? "up" : "down"} className={`ml-1 text-[10px] ${arrow === "up" ? "text-good" : "text-bad"}`}>{arrow === "up" ? "▲" : "▼"}</span>}
          </>
        );
        let tip: TipData | undefined;
        if (why && prev != null && delta !== 0) {
          const rows: DriverRow[] = why.map((f) => ({ project_id: f.id, project: f.project, form: f.name, current: f.months[i], previous: f.months[i - 1], delta: f.months[i] - f.months[i - 1] }));
          tip = tipFromRows(rows, delta, { previousTotal: prev, currentTotal: n, periods: months ? `${monthLabel(months[i - 1])} → ${monthLabel(months[i])}${i === partial ? " (so far; the month before is a full month)" : ""}` : undefined });
        }
        return (
          <td key={i} className={`whitespace-nowrap px-2 py-2 text-right tabular ${strong ? "font-semibold" : ""}`}
            style={n ? { backgroundColor: `rgba(63,196,126,${(0.04 + 0.22 * (n / max)).toFixed(3)})` } : undefined}
            title={prev == null || tip ? undefined : `${fmtInt(prev)} → ${fmtInt(n)} (${signed(delta)}) against the month before`}>
            {tip ? <DriverTip label={`Forms behind the change in ${monthLabel(months![i])}`} data={tip}>{shown}</DriverTip> : shown}
          </td>
        );
      })}
    </>
  );
}

/** Whole-year view: every form of every project, month against month. Follows the global filters. */
export function FormsMonthsTable() {
  const [metric, setMetric] = useState<MetricKey>("received");
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [allOpen, setAllOpen] = useState(false);
  const [text, setText] = useState("");
  const q = useFormsMonths(metric);
  const patch = useFilterStore((s) => s.patch);
  const d = q.data;
  const needle = text.trim().toLowerCase();

  const projects = useMemo(() => (d?.projects ?? []).map((p) => {
    if (!needle) return p;
    const hit = p.project.toLowerCase().includes(needle) || p.client.toLowerCase().includes(needle);
    const forms = hit ? p.forms : p.forms.filter((f) => f.form.toLowerCase().includes(needle));
    return forms.length ? { ...p, forms } : null;
  }).filter((p): p is NonNullable<typeof p> => p != null), [d, needle]);

  const toggle = (id: number) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const isOpen = (id: number) => allOpen || needle !== "" || open.has(id);
  const allForms = useMemo(() => (d?.projects ?? []).flatMap((p) => p.forms.map((f) => ({ name: f.form, project: p.project, id: p.project_id, months: f.months }))), [d]);
  const partial = d?.partial_month ? d.months.indexOf(d.partial_month) : -1;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Tabs label="Measure" value={metric} onChange={setMetric} items={METRICS.map((m) => ({ value: m.value, label: m.label }))} />
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Find a project, client or form…" aria-label="Find a project, client or form" className="max-w-xs" />
        <button className="rounded-lg border px-3 py-2 text-xs hover:border-primary" onClick={() => { setAllOpen((v) => !v); setOpen(new Set()); }}>
          {allOpen ? "Collapse all projects" : "Expand all projects"}
        </button>
        <span className="text-xs text-muted-foreground">{projects.length} projects · {fmtInt(projects.reduce((a, p) => a + p.forms.length, 0))} forms</span>
      </div>
      {d?.definition && <p className="mb-2 text-xs text-muted-foreground">Counted as: {d.definition}. ▲▼ = against the month before{partial >= 0 ? "; the month in progress is not marked" : ""}.</p>}

      {q.isError ? <QueryError error={q.error} /> : q.isLoading || !d ? <ChartSkeleton h={260} /> : (
        <div className="max-h-[36rem] overflow-auto rounded-xl border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Forms per project, month by month</caption>
            <thead className="sticky top-0 z-20 bg-muted/95 backdrop-blur"><tr>
              <th scope="col" className="sticky left-0 z-30 min-w-[16rem] bg-muted px-3 py-2 font-medium">Project / form</th>
              {d.months.map((m, i) => (
                <th key={m} scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">
                  {monthLabel(m)}{i === partial && <span className="block text-[10px] font-normal text-muted-foreground">so far</span>}
                </th>
              ))}
              <th scope="col" className="px-3 py-2 text-right font-medium">Total</th>
            </tr></thead>
            <tbody>
              <tr className="border-t bg-card/80">
                <th scope="row" className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-semibold">All shown</th>
                <MonthCells values={d.totals} partial={partial} strong months={d.months} why={allForms} />
                <td className="px-3 py-2 text-right font-semibold tabular">{fmtInt(d.totals.reduce((a, n) => a + n, 0))}</td>
              </tr>
              {projects.map((p) => (
                <Fragment key={p.project_id}>
                  <tr className="border-t bg-card/50">
                    <th scope="row" className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-medium">
                      <button className="mr-1 inline-flex align-middle text-muted-foreground" aria-expanded={isOpen(p.project_id)}
                        aria-label={`${isOpen(p.project_id) ? "Hide" : "Show"} forms of ${p.project}`} onClick={() => toggle(p.project_id)}>
                        {isOpen(p.project_id) ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                      <button className="text-primary hover:underline" onClick={() => patch({ project_id: p.project_id })}>{p.project}</button>
                      <span className="block pl-6 text-xs font-normal text-muted-foreground">{p.client} · {p.form_count} form{p.form_count === 1 ? "" : "s"}</span>
                    </th>
                    <MonthCells values={p.months} partial={partial} strong months={d.months}
                      why={p.forms.map((f) => ({ name: f.form, project: "", id: p.project_id, months: f.months }))} />
                    <td className="px-3 py-2 text-right font-semibold tabular">{fmtInt(p.total)}</td>
                  </tr>
                  {isOpen(p.project_id) && p.forms.map((f) => (
                    <tr key={f.form} className="border-t hover:bg-muted/40">
                      <th scope="row" className="sticky left-0 z-10 bg-card py-2 pl-10 pr-3 text-left font-normal"><span className="line-clamp-2" title={f.form}>{f.form}</span></th>
                      <MonthCells values={f.months} partial={partial} />
                      <td className="px-3 py-2 text-right tabular">{fmtInt(f.total)}</td>
                    </tr>
                  ))}
                </Fragment>
              ))}
              {projects.length === 0 && <tr><td colSpan={d.months.length + 2} className="px-3 py-8 text-center text-muted-foreground">No forms in this period</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
