"use client";
import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Layers } from "lucide-react";
import { Badge, Card, Input, Tabs } from "./ui/primitives";
import { Chart, COLORS, DEPTH, axes, solid, useChartColors } from "./chart";
import { ChartSkeleton, QueryError } from "./widgets";
import { useFormsCompare, useOverview } from "@/lib/hooks";
import { FormsMonthsTable } from "./forms-months-table";
import { DriverTip, tipFromRows } from "./driver-tip";
import { useFilterStore } from "@/lib/store";
import { fmtDate, fmtInt } from "@/lib/format";
import type { Change, FormsCompareForm, FormsCompareProject } from "@/lib/types";
import type { EChartsOption } from "echarts";

const tone = (c: Change) => (c.direction === "down" ? "bad" : c.direction === "up" ? "good" : "neutral");
const pct = (c: Change) => (c.pct_change == null ? (c.current > 0 ? "new" : "–") : `${c.pct_change > 0 ? "+" : c.pct_change < 0 ? "−" : ""}${Math.abs(c.pct_change).toFixed(1)}%`);

type Metric = "received" | "qc_completed";

/** "Project · form", but never "X · X" and never the project name twice ("Pizza Hut: B1 Pan · Pizza Hut: B1 Pan 30 Day"). */
function formLabel(project: string, form: string): string {
  const p = project.trim().toLowerCase(), f = form.trim().toLowerCase();
  return f === p || f.startsWith(p) ? form : `${project} · ${form}`;
}

/** On a project row the badge explains itself: it lists the forms of that project that moved the number. */
function Cell({ c, project, metric }: { c: Change; project?: FormsCompareProject; metric?: Metric }) {
  const badge = <Badge tone={tone(c)} className="ml-2 min-w-[3.5rem] justify-center">{pct(c)}</Badge>;
  const forms: FormsCompareForm[] = project?.forms ?? [];
  return (
    <td className="whitespace-nowrap px-3 py-2 text-right tabular">
      <span className="font-medium">{fmtInt(c.current)}</span>
      <span className="text-xs text-muted-foreground"> / {fmtInt(c.previous)}</span>
      {project && metric && c.delta !== 0 ? (
        <DriverTip label={`Forms behind the change of ${project.project}`}
          data={tipFromRows(forms.map((f) => ({ project_id: project.project_id, project: "", form: f.form, current: f[metric].current, previous: f[metric].previous, delta: f[metric].delta })),
            c.delta, { previousTotal: c.previous, currentTotal: c.current })}>{badge}</DriverTip>
      ) : badge}
    </td>
  );
}

/** Every form (form name) inside every project, this period against the previous period or last year. */
export function FormsCompareCard() {
  // a long period (a whole year, a quarter…) opens month by month: there is no equally long earlier period to compare with
  const [picked, setMode] = useState<"months" | "previous" | "yoy" | null>(null);
  const ov = useOverview();
  const days = ov.data ? (Date.parse(ov.data.period.to) - Date.parse(ov.data.period.from)) / 86_400_000 + 1 : 0;
  const mode = picked ?? (days > 62 ? "months" : "previous");
  const vs = mode === "yoy" ? "yoy" : "previous";
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [allOpen, setAllOpen] = useState(false);
  const [text, setText] = useState("");
  const q = useFormsCompare(vs, mode !== "months");
  const patch = useFilterStore((s) => s.patch);
  const c = useChartColors();
  const d = q.data;

  const needle = text.trim().toLowerCase();
  const projects = useMemo(() => (d?.projects ?? []).map((p) => {
    if (!needle) return p;
    const hit = p.project.toLowerCase().includes(needle) || p.client.toLowerCase().includes(needle);
    const forms = hit ? p.forms : p.forms.filter((f) => f.form.toLowerCase().includes(needle));
    return forms.length ? { ...p, forms } : null;
  }).filter((p): p is NonNullable<typeof p> => p != null), [d, needle]);

  const top = useMemo(() => projects.flatMap((p) => p.forms.map((f) => ({ name: formLabel(p.project, f.form), received: f.received })))
    .sort((a, b) => b.received.current + b.received.previous - (a.received.current + a.received.previous)).slice(0, 12), [projects]);

  const option = useMemo<EChartsOption>(() => ({
    legend: { show: true },
    grid: { left: 8, right: 24, top: 32, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "value", ...axes(c) },
    yAxis: { type: "category", inverse: true, data: top.map((r) => r.name), axisLabel: { color: c.text, width: 240, overflow: "truncate" }, axisLine: { lineStyle: { color: c.grid } } },
    series: [
      { name: "This period", type: "bar", barMaxWidth: 14, data: top.map((r) => r.received.current), itemStyle: { color: solid(COLORS.received), borderRadius: [0, 6, 6, 0], ...DEPTH } },
      { name: vs === "yoy" ? "Same dates last year" : "Previous period", type: "bar", barMaxWidth: 14, data: top.map((r) => r.received.previous), itemStyle: { color: solid("#8aa397"), borderRadius: [0, 6, 6, 0], ...DEPTH } },
    ],
  }), [top, c, vs]);

  const toggle = (id: number) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const isOpen = (id: number) => allOpen || needle !== "" || open.has(id);
  const formsTotal = projects.reduce((a, p) => a + p.forms.length, 0);

  return (
    <Card className="mt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold"><Layers className="h-4 w-4 text-primary" /> Forms inside each project — comparison</h2>
          <p className="max-w-3xl text-xs text-muted-foreground">
            {mode === "months" ? <>Month against month across the whole selected period. </> : <>
              {d ? <>{fmtDate(d.current.from)} – {fmtDate(d.current.to)} against {fmtDate(d.previous.from)} – {fmtDate(d.previous.to)}
                {d.partial && " (period still running: only the same number of days of the earlier one)"}. </> : null}
              Each cell is <i>this period / earlier period</i>. </>}
            Follows the filters above.
          </p>
        </div>
        <Tabs label="Compare" value={mode} onChange={setMode}
          items={[{ value: "months", label: "Month by month" }, { value: "previous", label: "Previous period" }, { value: "yoy", label: "Same dates last year" }]} />
      </div>

      {mode === "months" ? <FormsMonthsTable /> : q.isError ? <QueryError error={q.error} /> : q.isLoading ? <ChartSkeleton h={260} /> : (
        <>
          {top.length > 0 && (
            <Chart option={option} height={Math.max(220, top.length * 40 + 48)} ariaLabel={`Top ${top.length} forms by forms received, this period against the earlier one`} />
          )}

          <div className="mb-2 mt-3 flex flex-wrap items-center gap-2">
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Find a project, client or form…" aria-label="Find a project, client or form" className="max-w-xs" />
            <button className="rounded-lg border px-3 py-2 text-xs hover:border-primary" onClick={() => { setAllOpen((v) => !v); setOpen(new Set()); }}>
              {allOpen ? "Collapse all projects" : "Expand all projects"}
            </button>
            <span className="text-xs text-muted-foreground">{projects.length} projects · {fmtInt(formsTotal)} forms</span>
          </div>

          <div className="max-h-[36rem] overflow-auto rounded-xl border">
            <table className="w-full min-w-[52rem] text-left text-sm">
              <caption className="sr-only">Forms per project, this period against the earlier period</caption>
              <thead className="sticky top-0 z-10 bg-muted/90 backdrop-blur"><tr>
                <th scope="col" className="px-3 py-2 font-medium">Project / form</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Received</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">QC completed</th>
              </tr></thead>
              <tbody>
                {projects.map((p) => (
                  <Fragment key={p.project_id}>
                    <tr className="border-t bg-card/60">
                      <th scope="row" className="px-3 py-2 text-left font-medium">
                        <button className="mr-1 inline-flex align-middle text-muted-foreground" aria-expanded={isOpen(p.project_id)}
                          aria-label={`${isOpen(p.project_id) ? "Hide" : "Show"} forms of ${p.project}`} onClick={() => toggle(p.project_id)}>
                          {isOpen(p.project_id) ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </button>
                        <button className="text-primary hover:underline" onClick={() => patch({ project_id: p.project_id })}>{p.project}</button>
                        <span className="ml-2 text-xs font-normal text-muted-foreground">{p.client} · {p.form_count} form{p.form_count === 1 ? "" : "s"}</span>
                      </th>
                      <Cell c={p.received} project={p} metric="received" /><Cell c={p.qc_completed} project={p} metric="qc_completed" />
                    </tr>
                    {isOpen(p.project_id) && p.forms.map((f) => (
                      <tr key={f.form} className="border-t hover:bg-muted/40">
                        <th scope="row" className="py-2 pl-10 pr-3 text-left font-normal"><span className="line-clamp-2" title={f.form}>{f.form}</span></th>
                        <Cell c={f.received} /><Cell c={f.qc_completed} />
                      </tr>
                    ))}
                  </Fragment>
                ))}
                {projects.length === 0 && <tr><td colSpan={3} className="px-3 py-8 text-center text-muted-foreground">No forms in this period</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
