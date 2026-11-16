"use client";
import { useEffect, useMemo, useState } from "react";
import { TrendingDown } from "lucide-react";
import { Badge, Card, Tabs } from "./ui/primitives";
import { Chart, axes, useChartColors } from "./chart";
import { ChartSkeleton, QueryError } from "./widgets";
import { useMonthDrivers } from "@/lib/hooks";
import { useFilterStore } from "@/lib/store";
import { fmtInt } from "@/lib/format";
import type { DriverMonth, DriverProject } from "@/lib/types";
import type { EChartsOption } from "echarts";

const METRICS = [
  { value: "received", label: "Forms received" },
  { value: "edited", label: "Edited" },
  { value: "qc_completed", label: "QC completed" },
] as const;
type MetricKey = (typeof METRICS)[number]["value"];

const monthName = (iso: string, long = false) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { month: long ? "long" : "short", year: long ? "numeric" : "2-digit" });
const signed = (n: number) => (n > 0 ? `+${fmtInt(n)}` : n < 0 ? `−${fmtInt(-n)}` : "0");
const pctText = (p: number | null) => (p == null ? "new" : `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(p).toFixed(1)}%`);
const dirTone = (d: DriverMonth["direction"]) => (d === "down" ? "text-bad" : d === "up" ? "text-good" : "text-muted-foreground");

function ProjectList({ rows, tone, onOpen }: { rows: DriverProject[]; tone: "bad" | "good"; onOpen: (p: DriverProject) => void }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.delta)));
  return (
    <ul className="space-y-2">
      {rows.map((p) => (
        <li key={p.project_id} className="rounded-xl border bg-card/50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <button className="truncate text-left text-sm font-medium text-primary hover:underline" onClick={() => onOpen(p)}>{p.project}</button>
              <p className="text-xs text-muted-foreground">
                {p.client} · project total {fmtInt(p.previous)} → {fmtInt(p.current)}
                {p.net_delta !== p.delta && ` (net ${signed(p.net_delta)})`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {tone === "bad" && p.share_of_decline_pct != null && <Badge tone="bad">{p.share_of_decline_pct.toFixed(0)}% of the drop</Badge>}
              <span className={`text-sm font-semibold tabular ${tone === "bad" ? "text-bad" : "text-good"}`}>{signed(p.delta)}</span>
            </div>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className={`h-full rounded-full ${tone === "bad" ? "bg-bad" : "bg-good"}`} style={{ width: `${(100 * Math.abs(p.delta)) / max}%` }} />
          </div>
          <ul className="mt-2 divide-y text-xs">
            {p.forms.map((f) => (
              <li key={f.form} className="flex items-center justify-between gap-3 py-1">
                <span className="min-w-0 truncate" title={f.form}>{f.form}</span>
                <span className="shrink-0 tabular text-muted-foreground">
                  {fmtInt(f.previous)} → {fmtInt(f.current)}{" "}
                  <b className={tone === "bad" ? "text-bad" : "text-good"}>{signed(f.delta)}</b>
                </span>
              </li>
            ))}
            {p.form_count > p.forms.length && (
              <li className="py-1 text-muted-foreground">+ {p.form_count - p.forms.length} more form{p.form_count - p.forms.length === 1 ? "" : "s"}</li>
            )}
          </ul>
        </li>
      ))}
    </ul>
  );
}

/** Month by month: where did the volume fall, and which project / form was behind it. Follows the global filters. */
export function MonthDriversCard() {
  const [metric, setMetric] = useState<MetricKey>("received");
  const [picked, setPicked] = useState<string | null>(null);
  const q = useMonthDrivers(metric);
  const patch = useFilterStore((s) => s.patch);
  const c = useChartColors();
  const months = useMemo(() => q.data?.months ?? [], [q.data]);

  // default selection: the worst month, otherwise the latest one
  const worst = useMemo(() => months.filter((m) => m.delta < 0).sort((a, b) => a.delta - b.delta)[0], [months]);
  const sel = months.find((m) => m.month === picked) ?? worst ?? months[months.length - 1];
  useEffect(() => { if (picked && !months.some((m) => m.month === picked)) setPicked(null); }, [months, picked]);

  const downs = months.filter((m) => m.direction === "down").length;
  const label = METRICS.find((m) => m.value === metric)!.label.toLowerCase();

  const option = useMemo<EChartsOption>(() => ({
    grid: { left: 8, right: 12, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        const m = months[i];
        return `<b>${monthName(m.month, true)}</b>${m.partial ? " (so far)" : ""}<br/>${fmtInt(m.previous)} → ${fmtInt(m.current)} (${signed(m.delta)}, ${pctText(m.pct_change)})`;
      },
    },
    xAxis: { type: "category", data: months.map((m) => monthName(m.month)), ...axes(c), splitLine: { show: false } },
    yAxis: { type: "value", ...axes(c) },
    series: [{
      type: "bar", barMaxWidth: 34,
      data: months.map((m) => ({
        value: m.delta,
        itemStyle: { color: m.delta < 0 ? "#ff6b73" : m.delta > 0 ? "#3fc47e" : "#8aa397", borderRadius: m.delta < 0 ? [0, 0, 5, 5] : [5, 5, 0, 0],
          opacity: sel && m.month === sel.month ? 1 : 0.6, borderColor: sel && m.month === sel.month ? c.tipText : "transparent", borderWidth: 2 },
      })),
      label: { show: months.length <= 18, position: "top", color: c.text, formatter: (p: { value?: unknown }) => signed(Number(p.value)) },
    }],
  }), [months, sel, c]);

  return (
    <Card className="mt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <TrendingDown className="h-4 w-4 text-bad" /> Which month went down, and which project&apos;s form pulled it down
          </h2>
          <p className="max-w-3xl text-xs text-muted-foreground">
            Each bar is a calendar month against the month before it (the month in progress is compared with the same days of the last one).
            Follows the filters above (client, project, editor, status…). {q.data?.definition && <>Counted as: {q.data.definition}.</>}
          </p>
        </div>
        <Tabs label="Measure" value={metric} onChange={setMetric} items={METRICS.map((m) => ({ value: m.value, label: m.label }))} />
      </div>

      {q.isError ? <QueryError error={q.error} /> : q.isLoading ? <ChartSkeleton h={260} /> : months.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">No month in the selected period.</p>
      ) : (
        <>
          <p className="mb-2 text-sm" aria-live="polite">
            {downs === 0 ? <>No month had fewer {label} than the month before.</> : (
              <>
                <b className="text-bad">{downs}</b> of {months.length} month{months.length === 1 ? "" : "s"} had fewer {label} than the month before.
                {worst && worst.decliners[0] && (
                  <> Biggest fall: <b>{monthName(worst.month, true)}</b> ({signed(worst.delta)}), mostly <b>{worst.decliners[0].project}</b>
                    {worst.decliners[0].forms[0] && <> – <i>{worst.decliners[0].forms[0].form}</i></>}.</>
                )}
              </>
            )}
          </p>

          <Chart option={option} height={240} ariaLabel={`Monthly change in ${label}: ${months.map((m) => `${monthName(m.month)} ${signed(m.delta)}`).join(", ")}`}
            onPointClick={(p) => setPicked(months[p.dataIndex]?.month ?? null)} />

          <div role="tablist" aria-label="Month" className="mt-2 flex gap-1 overflow-x-auto pb-1">
            {months.map((m) => (
              <button key={m.month} role="tab" aria-selected={sel?.month === m.month} onClick={() => setPicked(m.month)}
                className={`shrink-0 rounded-lg border px-2.5 py-1 text-xs tabular transition ${sel?.month === m.month ? "border-primary bg-primary/15" : "bg-card/50 hover:border-primary"}`}>
                {monthName(m.month)} <span className={dirTone(m.direction)}>{signed(m.delta)}</span>
              </button>
            ))}
          </div>

          {sel && (
            <div className="mt-3">
              <h3 className="text-sm font-semibold">
                {monthName(sel.month, true)}{sel.partial && " (so far)"}: {fmtInt(sel.previous)} → {fmtInt(sel.current)}{" "}
                <span className={dirTone(sel.direction)}>({signed(sel.delta)}, {pctText(sel.pct_change)})</span>
              </h3>
              <p className="text-xs text-muted-foreground">
                Compared with {monthName(sel.previous_month, true)}{sel.partial && ", first days only"}.
                {sel.decliner_count > 0 ? <> {sel.decliner_count} project{sel.decliner_count === 1 ? "" : "s"} had forms that fell{sel.decliner_count > sel.decliners.length && ` (top ${sel.decliners.length} shown)`}.</> : null}
              </p>
              <div className="mt-3 grid gap-4 xl:grid-cols-[3fr_2fr]">
                <div>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-bad">Pulled it down</h4>
                  {sel.decliners.length === 0
                    ? <p className="rounded-xl border p-4 text-center text-sm text-muted-foreground">No project or form fell against the previous month.</p>
                    : <ProjectList rows={sel.decliners} tone="bad" onOpen={(p) => patch({ project_id: p.project_id })} />}
                </div>
                <div>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-good">Pushed it up</h4>
                  {sel.gainers.length === 0
                    ? <p className="rounded-xl border p-4 text-center text-sm text-muted-foreground">Nothing grew.</p>
                    : <ProjectList rows={sel.gainers} tone="good" onOpen={(p) => patch({ project_id: p.project_id })} />}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
