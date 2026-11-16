"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import * as Dd from "@radix-ui/react-dropdown-menu";
import { Check, Columns3, Download } from "lucide-react";
import { Button, Input, Select } from "@/components/ui/primitives";
import { Pager, RecordsTable } from "@/components/data-table";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ChartCard, PageHeader, QueryError } from "@/components/widgets";
import { api, buildQuery } from "@/lib/api";
import { useApiFilters, useMe } from "@/lib/hooks";
import { label } from "@/lib/format";
import type { RecordsResp } from "@/lib/types";

const METRICS = ["received", "edited", "finalised", "processed", "qc_completed", "pending_editing", "qc_pending"];

function Explorer() {
  const sp = useSearchParams();
  const f = useApiFilters();
  const { data: me } = useMe();
  const [metric, setMetric] = useState(sp.get("metric") ?? "");
  const [search, setSearch] = useState(sp.get("search") ?? "");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sort, setSort] = useState<string | undefined>();
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [cols, setCols] = useState<string[] | null>(null);

  const meta = useQuery({ queryKey: ["rec-cols"], queryFn: () => api<{ all: string[]; default: string[] }>("/records/columns"), staleTime: Infinity });
  // until the user picks columns, the API chooses the ones that are filled for the selected metric
  const q = useQuery({
    queryKey: ["explorer", f, metric, search, page, pageSize, sort, order, cols],
    queryFn: () => api<RecordsResp>("/records/forms", { ...f, metric, search, page, page_size: pageSize, sort, order, columns: cols?.join(",") }),
    placeholderData: keepPreviousData,
  });
  const columns = cols ?? q.data?.columns ?? meta.data?.default;
  useEffect(() => setPage(1), [metric, search, pageSize, JSON.stringify(f)]);

  const toggleSort = (k: string) => { if (sort === k) setOrder((o) => (o === "asc" ? "desc" : "asc")); else { setSort(k); setOrder("asc"); } };
  const canExport = me?.role === "manager" || me?.role === "admin";
  const exportHref = (format: string) => `/api/records/forms/export${buildQuery({ ...f, metric, search, sort, order, columns: columns?.join(","), format })}`;

  return (
    <>
      <PageHeader title="Data Explorer" subtitle="The records behind every number. Filters above apply; pick a metric to see exactly the forms counted in it">
        <Breadcrumbs />
      </PageHeader>
      <ChartCard title="Forms" subtitle={q.data ? `${q.data.total.toLocaleString("en-US")} records · ${q.data.period.from} to ${q.data.period.to}` : undefined}
        action={
          <div className="flex flex-wrap items-end gap-2">
            <Select label="Counted in" className="w-44" value={metric} onChange={setMetric} placeholder="Any" options={METRICS.map((m) => ({ value: m, label: label(m) }))} />
            <Input placeholder="Search id, location, editor…" aria-label="Search records" className="h-9 w-56" value={search} onChange={(e) => setSearch(e.target.value)} />
            <Dd.Root>
              <Dd.Trigger asChild><Button size="sm"><Columns3 className="h-4 w-4" /> Columns</Button></Dd.Trigger>
              <Dd.Portal>
                <Dd.Content align="end" className="glass z-50 max-h-80 w-56 overflow-auto p-1">
                  {meta.data?.all.map((c) => {
                    const on = columns?.includes(c) ?? false;
                    return (
                      <Dd.CheckboxItem key={c} checked={on} onSelect={(e) => e.preventDefault()}
                        onCheckedChange={(v) => setCols((columns ?? []).filter((x) => x !== c).concat(v ? [c] : []).sort((a, b) => meta.data!.all.indexOf(a) - meta.data!.all.indexOf(b)))}
                        className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted">
                        <span className="grid h-4 w-4 place-items-center rounded border">{on && <Check className="h-3 w-3" />}</span> {label(c)}
                      </Dd.CheckboxItem>
                    );
                  })}
                </Dd.Content>
              </Dd.Portal>
            </Dd.Root>
            <Select label="Rows" className="w-24" value={pageSize} onChange={(v) => setPageSize(Number(v) || 25)} placeholder="25" options={[25, 50, 100, 200].map((n) => ({ value: n, label: String(n) }))} />
            {canExport ? (
              <>
                <a href={exportHref("csv")} className="inline-flex h-9 items-center gap-1 rounded-xl border bg-card/60 px-3 text-sm hover:bg-muted"><Download className="h-4 w-4" /> CSV</a>
                <a href={exportHref("xlsx")} className="inline-flex h-9 items-center gap-1 rounded-xl border bg-card/60 px-3 text-sm hover:bg-muted"><Download className="h-4 w-4" /> Excel</a>
              </>
            ) : <span className="text-xs text-muted-foreground" title="Export needs the manager role">Export: manager+</span>}
          </div>
        }>
        {q.isError ? <QueryError error={q.error} /> : (
          <>
            <RecordsTable caption="Forms" columns={q.data?.columns ?? []} rows={q.data?.rows ?? []} sort={sort} order={order} onSort={toggleSort} />
            <Pager page={page} pageSize={pageSize} total={q.data?.total ?? 0} onPage={setPage} />
          </>
        )}
      </ChartCard>
    </>
  );
}

export default function ExplorerPage() {
  return <Suspense><Explorer /></Suspense>;
}
