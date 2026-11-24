"use client";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ChartCard, ChartSkeleton, PageHeader, QueryError } from "@/components/widgets";
import { KpiHero } from "@/components/kpi-hero";
import { useWide } from "@/lib/visual";
import { RankBars } from "@/components/charts";
import { useQc } from "@/lib/hooks";
import { useDrill } from "@/lib/drill";
import { useFilterStore } from "@/lib/store";

export default function QcPage() {
  const qc = useQc();
  const show = useDrill((s) => s.show);
  const patch = useFilterStore((s) => s.patch);
  const wide = useWide();

  return (
    <>
      <PageHeader title="QC" subtitle="Who did how much QC and when, and the QC backlog">
        <Breadcrumbs />
      </PageHeader>
      {qc.isError && <QueryError error={qc.error} />}

      <KpiHero loading={qc.isLoading} wide={wide} items={[
        { key: "qcd", label: "QC completed", tone: "good", hint: "QC Date in period", color: "#15665a", value: qc.data?.totals.qc_completed, onClick: () => show({ metric: "qc_completed", title: "QC completed" }) },
        { key: "qcp", label: "QC pending", tone: "warn", hint: "Handled in period, no QC yet", color: "#b91c1c", value: qc.data?.totals.qc_pending, onClick: () => show({ metric: "qc_pending", title: "QC pending" }) },
        { key: "pct", label: "QC workload cleared %", tone: "brand", hint: "done ÷ (done + pending)", color: "#1f7a4d", value: qc.data?.totals.qc_pct == null ? undefined : Math.round(qc.data.totals.qc_pct) },
      ]} />

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartCard title="QC completed by member" subtitle="Who completed how much QC in the selected period">
          {qc.isLoading ? <ChartSkeleton /> : (
            <RankBars rows={(qc.data?.members ?? []).map((r) => ({ id: r.id, name: r.name, values: { qc_completed: r.qc_completed } }))}
              keys={["qc_completed"]} />
          )}
        </ChartCard>
        <ChartCard title="QC backlog by project" subtitle="Forms waiting for QC at period end (QC-enabled projects only)">
          {qc.isLoading ? <ChartSkeleton /> : (
            <RankBars rows={(qc.data?.backlog_by_project ?? []).map((r) => ({ id: r.project_id, name: r.project, values: { qc_pending: r.qc_pending, qc_completed: r.qc_completed } }))}
              keys={["qc_pending", "qc_completed"]} onClick={(r) => r.id && patch({ project_id: r.id })} />
          )}
        </ChartCard>
      </div>
    </>
  );
}
