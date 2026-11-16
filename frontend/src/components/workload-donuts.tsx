"use client";
import dynamic from "next/dynamic";
import { Skeleton } from "./ui/primitives";
import { Boundary } from "./three/boundary";
import { Donut as Donut2D } from "./charts";
import { COLORS } from "./chart";
import { ChartCard } from "./widgets";
import { useUse3D } from "@/lib/visual";
import { fmtInt } from "@/lib/format";
import type { Metrics, MetricKey } from "@/lib/types";
import type { DonutDef } from "./three/donut-scene";

const DonutScene = dynamic(() => import("./three/donut-scene"), { ssr: false, loading: () => <Skeleton className="h-[440px] w-full" /> });

/** Editing vs QC completion: two rotating 3D donuts, or flat 2D donuts when 3D is unavailable. */
export function WorkloadDonuts({ m, onSlice }: { m?: Metrics; onSlice: (metric: MetricKey, title: string) => void }) {
  const { use3D } = useUse3D();
  if (!m) return <ChartCard title="Workload"><Skeleton className="h-[300px] w-full" /></ChartCard>;

  const pct = (v: number | null) => (v == null ? "–" : `${Math.round(v)}%`);
  const donuts: DonutDef[] = [
    { title: "Editing", center: pct(m.editing_pct), slices: [
      { name: "Handled", value: m.processed, color: COLORS.edited, onClick: () => onSlice("processed", "Forms handled") },
      { name: "Pending editing", value: m.pending_editing, color: COLORS.pending, onClick: () => onSlice("pending_editing", "Pending editing") },
    ] },
    { title: "QC", center: pct(m.qc_pct), slices: [
      { name: "QC completed", value: m.qc_completed, color: COLORS.qc, onClick: () => onSlice("qc_completed", "QC completed") },
      { name: "QC pending", value: m.qc_pending, color: COLORS.bad, onClick: () => onSlice("qc_pending", "QC pending") },
    ] },
  ];

  const flat = (
    <div className="grid gap-4">
      {donuts.map((d) => (
        <ChartCard key={d.title} title={`${d.title} workload`}>
          <Donut2D centerLabel={d.center} height={190} onClick={(n) => { const s = d.slices.find((x) => x.name === n); s?.onClick?.(); }}
            data={d.slices.map((s) => ({ name: s.name, value: s.value, color: s.color }))} />
        </ChartCard>
      ))}
    </div>
  );
  if (!use3D) return flat;

  return (
    <Boundary fallback={flat}>
      <ChartCard title="Editing vs QC workload" subtitle="Hover a slice for details, click for its records">
        <DonutScene donuts={donuts} />
        <details className="mt-1 text-sm">
          <summary className="cursor-pointer text-muted-foreground">View as table</summary>
          <table className="mt-2 w-full text-left">
            <caption className="sr-only">Editing and QC workload</caption>
            <tbody>
              {donuts.flatMap((d) => d.slices.map((s) => (
                <tr key={s.name} className="border-t"><th scope="row" className="py-1 font-normal">{d.title}: {s.name}</th><td className="py-1 text-right tabular-nums">{fmtInt(s.value)}</td></tr>
              )))}
            </tbody>
          </table>
        </details>
      </ChartCard>
    </Boundary>
  );
}
