"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { CheckCircle2, RefreshCw, TriangleAlert } from "lucide-react";
import { Badge, Button, Card, Select } from "@/components/ui/primitives";
import { Pager } from "@/components/data-table";
import { ChartCard, PageHeader, QueryError } from "@/components/widgets";
import { api, post } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import { fmtDate, fmtInt } from "@/lib/format";
import type { HealthResp, SyncStatus } from "@/lib/types";

const sevTone = (s: string) => (s === "error" ? "bad" : s === "warn" ? "warn" : "neutral");

export default function HealthPage() {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<HealthResp>("/health/data") });
  const sync = useQuery({
    queryKey: ["sync-status"], queryFn: () => api<SyncStatus>("/sync/status"),
    refetchInterval: (q) => (q.state.data?.running ? 1500 : false),
  });
  const run = useMutation({
    mutationFn: (force: boolean) => post("/sync", undefined, { force }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sync-status"] }),
  });
  // when a run finishes, every number on every page may have changed
  const running0 = useRef(false);
  useEffect(() => {
    if (running0.current && sync.data && !sync.data.running) qc.invalidateQueries();
    running0.current = !!sync.data?.running;
  }, [sync.data, qc]);

  const [type, setType] = useState("");
  const [sev, setSev] = useState("");
  const [page, setPage] = useState(1);
  const issues = useQuery({
    queryKey: ["issues", type, sev, page, sync.data?.last?.id, sync.data?.running],
    queryFn: () => api<{ total: number; rows: { id: number; severity: string; type: string; file: string | null; row_no: number | null; detail: string | null }[] }>("/health/issues", { type, severity: sev, page, page_size: 15 }),
    placeholderData: keepPreviousData,
  });

  const canSync = me?.role === "manager" || me?.role === "admin";
  const h = health.data;
  const last = sync.data?.last;
  const running = sync.data?.running;

  return (
    <>
      <PageHeader title="Data health" subtitle="Duplicates, missing values, unmapped columns and the state of the last sync" />
      {(health.isError || sync.isError) && <QueryError error={health.error ?? sync.error} />}

      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">Sync</h2>
            <p className="text-sm text-muted-foreground">
              Source: <Badge tone="brand">{sync.data?.data_source ?? "…"}</Badge>
              {last && <> · last run #{last.id} <Badge tone={last.status === "ok" ? "good" : last.status === "running" ? "brand" : "warn"}>{last.status}</Badge> {last.finished_at && `finished ${fmtDate(last.finished_at)}`}</>}
            </p>
            {running && last && (
              <div className="mt-2" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(last.progress_pct ?? 0)} aria-label="Sync progress">
                <div className="h-2 overflow-hidden rounded-full bg-muted"><div className="bg-brand h-full transition-all" style={{ width: `${last.progress_pct ?? 0}%` }} /></div>
                <p className="mt-1 text-xs text-muted-foreground">{last.files_scanned} of {last.files_total ?? "?"} files · {fmtInt(last.rows_upserted)} rows</p>
              </div>
            )}
            {!running && last && <p className="mt-1 text-xs text-muted-foreground">{last.files_changed} of {last.files_total ?? last.files_scanned} files changed · {fmtInt(last.rows_upserted)} rows · {fmtInt(last.rows_rejected)} rejected</p>}
            {last?.error_text && <p role="alert" className="mt-1 text-sm text-bad">{last.error_text}</p>}
          </div>
          {canSync && (
            <div className="flex gap-2">
              <Button variant="brand" disabled={running || run.isPending} onClick={() => run.mutate(false)}><RefreshCw className={`h-4 w-4 ${running ? "animate-spin" : ""}`} /> Sync now</Button>
              <Button disabled={running || run.isPending} onClick={() => run.mutate(true)} title="Re-read every file, even unchanged ones">Full re-sync</Button>
            </div>
          )}
        </div>
        {run.isError && <div className="mt-3"><QueryError error={run.error} /></div>}
      </Card>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {(h?.checks ?? []).map((c) => (
          <Card key={c.key} className="p-4">
            <p className="text-xs text-muted-foreground">{c.label}</p>
            <p className="mt-2 flex items-center gap-2 text-2xl font-semibold tabular">
              {c.count === 0 ? <CheckCircle2 className="h-5 w-5 text-good" aria-label="OK" /> : <TriangleAlert className="h-5 w-5 text-warn" aria-label="Needs attention" />}
              {fmtInt(c.count)}
            </p>
            <p className="text-xs text-muted-foreground">{c.pct}% of {fmtInt(h?.forms_total)} forms</p>
          </Card>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <ChartCard title="Unmapped columns" subtitle="Headers the mapper did not recognise (kept in extra data)">
          <TagList items={h?.unmapped_columns} empty="All columns mapped." />
        </ChartCard>
        <ChartCard title="Unmapped statuses" subtitle="Values missing from the status map (loaded as-is)">
          <TagList items={h?.unmapped_statuses} empty="All statuses mapped." />
        </ChartCard>
        <ChartCard title="Files with errors">
          <TagList items={h?.files_with_errors.map((f) => f.name)} empty="No failing files." />
        </ChartCard>
      </div>

      <ChartCard className="mt-4" title="Source columns kept as extra data"
        subtitle="Every column of your sheets that is not part of the standard fields is still loaded: its values are stored with each record (Data Explorer → Columns → Other columns). Nothing is dropped.">
        <div className="max-h-80 overflow-auto rounded-xl border">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <caption className="sr-only">Source columns kept as extra data</caption>
            <thead className="sticky top-0 bg-muted/90 backdrop-blur"><tr>
              {["Column header (as written in the sheet)", "Loaded into", "Rows with a value", "Tabs"].map((x) => <th key={x} scope="col" className="px-3 py-2 font-medium">{x}</th>)}
            </tr></thead>
            <tbody>
              {(h?.extra_columns ?? []).map((c) => (
                <tr key={`${c.kind}-${c.header}`} className="border-t">
                  <th scope="row" className="px-3 py-1.5 text-left font-medium">{c.header}</th>
                  <td className="px-3 py-1.5"><Badge>{c.kind}</Badge></td>
                  <td className="px-3 py-1.5 tabular">{fmtInt(c.rows)}</td>
                  <td className="px-3 py-1.5 tabular">{fmtInt(c.tabs)}</td>
                </tr>
              ))}
              {(h?.extra_columns?.length ?? 0) === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">No extra columns.</td></tr>}
            </tbody>
          </table>
        </div>
      </ChartCard>

      <ChartCard className="mt-4" title="Headers repaired from the data" subtitle="Tabs whose Input Date header was misspelt or junk ('Inpute Date', 'VIEW', 'kya' …); the column was recognised from its date values">
        <TagList items={h?.header_repairs} empty="No repairs needed." />
      </ChartCard>

      <ChartCard className="mt-4" title="Issues from the latest sync"
        action={<div className="flex gap-2">
          <Select label="Type" className="w-44" value={type} onChange={(v) => { setType(v); setPage(1); }} options={(h?.issues_last_sync ?? []).map((i) => ({ value: i.type, label: `${i.type} (${i.count})` })).filter((o, i, a) => a.findIndex((x) => x.value === o.value) === i)} />
          <Select label="Severity" className="w-32" value={sev} onChange={(v) => { setSev(v); setPage(1); }} options={["error", "warn", "info"].map((s) => ({ value: s, label: s }))} />
        </div>}>
        <div className="overflow-auto rounded-xl border">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <caption className="sr-only">Sync issues</caption>
            <thead className="bg-muted/80"><tr>{["Severity", "Type", "File", "Row", "Detail"].map((x) => <th key={x} scope="col" className="px-3 py-2 font-medium">{x}</th>)}</tr></thead>
            <tbody>
              {(issues.data?.rows ?? []).map((r) => (
                <tr key={r.id} className="border-t">
                  <td className="px-3 py-2"><Badge tone={sevTone(r.severity) as "bad" | "warn" | "neutral"}>{r.severity}</Badge></td>
                  <td className="px-3 py-2">{r.type}</td>
                  <td className="max-w-[16rem] truncate px-3 py-2" title={r.file ?? ""}>{r.file ?? "–"}</td>
                  <td className="px-3 py-2 tabular">{r.row_no ?? "–"}</td>
                  <td className="px-3 py-2 text-muted-foreground">{r.detail}</td>
                </tr>
              ))}
              {(issues.data?.rows.length ?? 0) === 0 && <tr><td colSpan={5} className="px-3 py-10 text-center text-muted-foreground">No issues.</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} pageSize={15} total={issues.data?.total ?? 0} onPage={setPage} />
      </ChartCard>
    </>
  );
}

function TagList({ items, empty }: { items?: string[]; empty: string }) {
  if (!items?.length) return <p className="flex items-center gap-2 py-4 text-sm text-muted-foreground"><CheckCircle2 className="h-4 w-4 text-good" /> {empty}</p>;
  return <ul className="flex max-h-40 flex-wrap gap-1.5 overflow-auto">{items.map((i) => <li key={i}><Badge>{i}</Badge></li>)}</ul>;
}
