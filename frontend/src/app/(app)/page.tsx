"use client";
import { useState } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { Badge, Card, Tabs } from "@/components/ui/primitives";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ChartCard, ChartSkeleton, PageHeader, QueryError, RingStat } from "@/components/widgets";
import { RankBars, TrendChart } from "@/components/charts";
import { KpiHero } from "@/components/kpi-hero";
import { WorkloadDonuts } from "@/components/workload-donuts";
import { QualityCard } from "@/components/quality-card";
import { MonthDriversCard } from "@/components/month-drivers-card";
import { FormsCompareCard } from "@/components/forms-compare-card";
import { Lazy } from "@/components/lazy";
import { useWide } from "@/lib/visual";
import { useAlerts, useBreakdown, useOverview, useTimeseries } from "@/lib/hooks";
import { useDrill } from "@/lib/drill";
import { useFilterStore } from "@/lib/store";
import { hrefWith } from "@/lib/filters";
import { fmtDate, fmtInt } from "@/lib/format";
import { allowedGranularities, autoGranularity, effectiveGranularity, GRANULARITIES, GRAN_LABEL, Granularity } from "@/lib/period";
import type { MetricKey } from "@/lib/types";

// The first five are the 3D hero tiles (order matters); any further tile rides in the hero footer.
// Colours are darkened so white text on the 3D tiles keeps AA contrast.
const KPIS: { key: MetricKey; label: string; tone: "brand" | "good" | "warn" | "bad"; hint: string; color: string }[] = [
  { key: "received", label: "Forms received", tone: "brand", hint: "Input Date in period", color: "#1f7a4d" },
  { key: "qc_completed", label: "QC completed", tone: "good", hint: "QC Date in period", color: "#15665a" },
  { key: "qc_pending", label: "QC pending", tone: "bad", hint: "Handled in period, no QC yet", color: "#b91c1c" },
  { key: "finalised", label: "Finalised", tone: "good", hint: "Handled (Transaction Date) in period", color: "#166534" },
];

export default function OverallPage() {
  const ov = useOverview();
  const [gran, setGran] = useState<Granularity | null>(null);
  const filters = useFilterStore((s) => s.filters);
  const allowed = allowedGranularities(filters, ov.data?.period);
  const g = effectiveGranularity(gran, autoGranularity(ov.data?.period), allowed);
  const ts = useTimeseries(g);
  const clients = useBreakdown("client");
  const projects = useBreakdown("project");
  const alerts = useAlerts();
  // "pending editing is growing" alerts are about the Pending-editing status, which is no longer shown
  const shownAlerts = (alerts.data?.alerts ?? []).filter((a) => a.type !== "pending_growth");
  const show = useDrill((s) => s.show);
  const patch = useFilterStore((s) => s.patch);
  const m = ov.data?.metrics;
  const wide = useWide();

  return (
    <>
      <PageHeader title="Overall performance"
        subtitle={ov.data ? `${fmtDate(ov.data.period.from)} – ${fmtDate(ov.data.period.to)}` : "Loading…"}>
        <Breadcrumbs />
      </PageHeader>

      {ov.isError && <QueryError error={ov.error} />}

      <KpiHero loading={ov.isLoading} wide={wide}
        items={KPIS.map((k) => ({ key: k.key, label: k.label, tone: k.tone, hint: k.hint, color: k.color, value: m?.[k.key],
          onClick: m ? () => show({ metric: k.key, title: k.label }) : undefined }))} />

      <section aria-label="Completion" className="mt-3 grid gap-3 sm:grid-cols-2">
        <RingStat label="QC workload cleared" pct={m?.qc_pct} tone="good"
          detail={m ? `${fmtInt(m.qc_completed)} done · ${fmtInt(m.qc_pending)} pending` : undefined} />
        <RingStat label="Received forms processed" pct={m?.completion_pct} tone="good"
          detail={m ? `of ${fmtInt(m.received)} received in the period` : undefined} />
      </section>

      <Lazy height={320}><QualityCard /></Lazy>
      <Lazy height={320}><MonthDriversCard /></Lazy>
      <Lazy height={320}><FormsCompareCard /></Lazy>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Activity over time" subtitle="Each line is counted by its own date"
          action={<Tabs label="Granularity" value={g} onChange={setGran} items={GRANULARITIES.map((x) => ({ value: x, label: GRAN_LABEL[x], disabled: !allowed.includes(x), hint: "Longer than the selected period" }))} />}>
          {ts.isLoading ? <ChartSkeleton /> : ts.isError ? <QueryError error={ts.error} /> : (
            <TrendChart points={ts.data!.points} granularity={g} height={320} />
          )}
        </ChartCard>

        <WorkloadDonuts m={m} onSlice={(metric, title) => show({ metric, title })} />

        <ChartCard title="By client" subtitle="Click a bar to drill into that client">
          {clients.isLoading ? <ChartSkeleton /> : (
            <RankBars rows={(clients.data?.rows ?? []).map((r) => ({ id: r.id, name: r.name, values: { received: r.received, qc_completed: r.qc_completed } }))}
              keys={["received", "qc_completed"]} onClick={(r) => r.id && patch({ client_id: r.id, project_id: undefined })} />
          )}
        </ChartCard>

        <ChartCard title="Top projects by volume" subtitle="Click a bar to open the project">
          {projects.isLoading ? <ChartSkeleton /> : (
            <RankBars rows={(projects.data?.rows ?? []).map((r) => ({ id: r.id, name: r.name, values: { received: r.received } }))}
              keys={["received"]} limit={10} onClick={(r) => r.id && patch({ project_id: r.id })} />
          )}
        </ChartCard>

        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><AlertTriangle className="h-4 w-4 text-warn" /> Needs attention</h2>
            <Link href={hrefWith("/time", filters)} className="text-xs text-primary hover:underline">All comparisons</Link>
          </div>
          {alerts.isLoading ? <ChartSkeleton h={160} /> : shownAlerts.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">No alerts for the last complete month.</p>
          ) : (
            <ul className="space-y-2">
              {shownAlerts.slice(0, 6).map((a, i) => (
                <li key={i} className="rounded-xl border bg-card/50 p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{a.project}</span>
                    <Badge tone={a.severity === "high" ? "bad" : "warn"}>{a.type.replace(/_/g, " ")}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{a.client} · {a.detail}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
