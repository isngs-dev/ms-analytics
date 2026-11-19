"use client";
import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Badge } from "@/components/ui/primitives";
import { BarCity } from "@/components/bar-city";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { MetricTable } from "@/components/metric-table";
import { ChartCard, ChartSkeleton, KpiCard, PageHeader, QueryError, RingStat } from "@/components/widgets";
import { RankBars, TrendChart } from "@/components/charts";
import { Tabs } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useApiFilters, useBreakdown } from "@/lib/hooks";
import { useDrill } from "@/lib/drill";
import { useFilterStore } from "@/lib/store";
import type { BreakRow, Metrics, MetricKey, SeriesPoint } from "@/lib/types";

interface ProjectDetail {
  project: { id: number; name: string; client_id: number; qc_applicable: boolean };
  metrics: Metrics; by_editor: BreakRow[]; by_form: BreakRow[]; trend: SeriesPoint[];
}

export default function ClientsPage() {
  const f = useFilterStore((s) => s.filters);
  const patch = useFilterStore((s) => s.patch);
  const level = f.project_id ? "project" : f.client_id ? "client" : "overall";

  return (
    <>
      <PageHeader title="Clients & projects"
        subtitle={level === "overall" ? "Pick a client to see its projects, then a project for its detail" : level === "client" ? "Projects of the selected client" : "Project detail"}>
        <Breadcrumbs />
      </PageHeader>
      <div className="mb-4"><BarCity /></div>
      {level === "project" ? <ProjectView id={f.project_id!} /> : (
        <ListView by={level === "overall" ? "client" : "project"}
          onPick={(r) => r.id != null && (level === "overall" ? patch({ client_id: r.id, project_id: undefined }) : patch({ project_id: r.id }))} />
      )}
    </>
  );
}

function ListView({ by, onPick }: { by: "client" | "project"; onPick: (r: BreakRow) => void }) {
  const q = useBreakdown(by);
  const rows = q.data?.rows ?? [];
  return (
    <div className="space-y-4">
      {q.isError && <QueryError error={q.error} />}
      <ChartCard title={by === "client" ? "All clients" : "All projects"} subtitle="Received, finalised, QC and completion % for the selected period">
        {q.isLoading ? <ChartSkeleton h={200} /> : (
          <MetricTable rows={rows} firstLabel={by === "client" ? "Client" : "Project"} onRow={onPick} showParent={by === "project"} caption={`Metrics by ${by}`} />
        )}
      </ChartCard>
    </div>
  );
}

function ProjectView({ id }: { id: number }) {
  const f = useApiFilters();
  const patch = useFilterStore((s) => s.patch);
  const show = useDrill((s) => s.show);
  const [g, setG] = useState<"week" | "month">("month");
  const q = useQuery({
    queryKey: ["project", id, f],
    queryFn: () => api<ProjectDetail>(`/analytics/projects/${id}`, f),
    placeholderData: keepPreviousData,
  });
  if (q.isError) return <QueryError error={q.error} />;
  const d = q.data;
  const m = d?.metrics;
  const KP: [MetricKey, string][] = [["received", "Received"], ["qc_completed", "QC completed"], ["qc_pending", "QC pending"]];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold">{d?.project.name}</h2>
        {d && <Badge tone={d.project.qc_applicable ? "brand" : "neutral"}>{d.project.qc_applicable ? "QC applicable" : "No QC"}</Badge>}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {KP.map(([k, l]) => <KpiCard key={k} label={l} value={m?.[k]} loading={q.isLoading} tone={k.includes("pending") ? "warn" : "brand"} onClick={() => show({ metric: k, title: `${d?.project.name}: ${l}` })} />)}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <RingStat label="QC workload cleared" pct={m?.qc_pct} tone="good" detail={m ? `${m.qc_completed} done · ${m.qc_pending} pending` : undefined} />
        <RingStat label="Received forms processed" pct={m?.completion_pct} tone="good" detail={m ? `of ${m.received} received` : undefined} />
      </div>
      <ChartCard title="Trend" action={<Tabs label="Granularity" value={g} onChange={setG} items={[{ value: "week", label: "Weekly" }, { value: "month", label: "Monthly" }]} />}>
        {q.isLoading ? <ChartSkeleton /> : <TrendChart points={d!.trend} granularity={g} />}
      </ChartCard>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Editors on this project" subtitle="Click a bar to focus on an editor">
          <RankBars rows={(d?.by_editor ?? []).map((r) => ({ id: r.id, name: r.name, values: { finalised: r.finalised } }))}
            keys={["finalised"]} stacked onClick={(r) => r.id && patch({ editor_id: r.id })} />
        </ChartCard>
        <ChartCard title="Forms in this project">
          <RankBars rows={(d?.by_form ?? []).map((r) => ({ name: r.name, values: { received: r.received } }))} keys={["received"]} />
        </ChartCard>
      </div>
    </div>
  );
}
