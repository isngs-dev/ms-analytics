"use client";
import { useState } from "react";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { MetricTable } from "@/components/metric-table";
import { ChartCard, ChartSkeleton, PageHeader, QueryError } from "@/components/widgets";
import { KpiHero } from "@/components/kpi-hero";
import { useWide } from "@/lib/visual";
import { Donut, RankBars, TrendChart } from "@/components/charts";
import { COLORS, PALETTE } from "@/components/chart";
import { Tabs } from "@/components/ui/primitives";
import { useEditorDetail, useEditors } from "@/lib/hooks";
import { useDrill } from "@/lib/drill";
import { useFilterStore } from "@/lib/store";
import { fmtInt } from "@/lib/format";

export default function EditorsPage() {
  const f = useFilterStore((s) => s.filters);
  const patch = useFilterStore((s) => s.patch);
  const show = useDrill((s) => s.show);
  const q = useEditors();
  const [g, setG] = useState<"day" | "week" | "month">("week");
  const detail = useEditorDetail(f.editor_id, g);
  const rows = q.data?.editors ?? [];
  const t = q.data?.totals;
  const wide = useWide();

  return (
    <>
      <PageHeader title="Editor productivity" subtitle="Forms handled (any outcome) and finalised per editor">
        <Breadcrumbs />
      </PageHeader>
      {q.isError && <QueryError error={q.error} />}

      <KpiHero loading={q.isLoading} wide={wide} items={[
        { key: "processed", label: "Forms handled", tone: "brand", hint: "Any outcome in period", color: "#1f7a4d", value: t?.processed, onClick: () => show({ metric: "processed", title: "Forms handled" }) },
        { key: "editors", label: "Active editors", tone: "good", hint: "With work in period", color: "#15665a", value: q.isLoading ? undefined : rows.length },
      ]} />

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Editor comparison" subtitle="Click a bar to focus on that editor">
          {q.isLoading ? <ChartSkeleton /> : (
            <RankBars rows={rows.map((r) => ({ id: r.id, name: r.name, values: { processed: r.processed } }))}
              keys={["processed"]} limit={14} onClick={(r) => r.id && patch({ editor_id: r.id })} />
          )}
        </ChartCard>
        <ChartCard title="iSN team vs freelancers" subtitle="Share of forms handled">
          {q.isLoading ? <ChartSkeleton /> : (
            <Donut data={(q.data?.by_type ?? []).map((r, i) => ({ name: r.name, value: r.processed, color: PALETTE[i % PALETTE.length] }))} />
          )}
        </ChartCard>
      </div>

      {f.editor_id && (
        <section aria-label="Selected editor" className="mt-4 space-y-4">
          <h2 className="text-lg font-semibold"><span className="text-gradient">{detail.data?.editor.name ?? "Editor"}</span></h2>
          {detail.isError && <QueryError error={detail.error} />}
          <div className="grid gap-4 xl:grid-cols-3">
            <ChartCard className="xl:col-span-2" title="Output over time" subtitle="Finalised by date"
              action={<Tabs label="Granularity" value={g} onChange={setG} items={[{ value: "day", label: "Daily" }, { value: "week", label: "Weekly" }, { value: "month", label: "Monthly" }]} />}>
              {detail.isLoading ? <ChartSkeleton /> : <TrendChart points={detail.data!.output} granularity={g} keys={["finalised"]} bars />}
            </ChartCard>
            <ChartCard title="Contribution by client">
              {detail.isLoading ? <ChartSkeleton /> : (
                <Donut data={(detail.data?.by_client ?? []).map((r, i) => ({ name: r.name, value: r.processed, color: PALETTE[i % PALETTE.length] }))} />
              )}
            </ChartCard>
          </div>
          <ChartCard title="Contribution by project" subtitle={`${fmtInt(detail.data?.metrics.processed)} forms handled in the period`}>
            {detail.isLoading ? <ChartSkeleton h={200} /> : (
              <MetricTable rows={detail.data!.by_project} firstLabel="Project" showParent caption="Editor contribution by project" />
            )}
          </ChartCard>
        </section>
      )}

      <ChartCard className="mt-4" title="All editors" subtitle="Click a row to focus on that editor">
        {q.isLoading ? <ChartSkeleton h={200} /> : (
          <MetricTable rows={rows} firstLabel="Editor" caption="Editors" onRow={(r) => r.id && patch({ editor_id: r.id })} />
        )}
      </ChartCard>
    </>
  );
}
