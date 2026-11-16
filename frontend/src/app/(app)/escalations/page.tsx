"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { Badge, Button, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/dialog";
import { Pager } from "@/components/data-table";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ChartCard, ChartSkeleton, PageHeader, QueryError } from "@/components/widgets";
import { KpiHero } from "@/components/kpi-hero";
import { useWide } from "@/lib/visual";
import { RankBars } from "@/components/charts";
import { api, patch as apiPatch } from "@/lib/api";
import { useApiFilters, useEscSummary, useMe } from "@/lib/hooks";
import { useFilterStore } from "@/lib/store";
import { fmtDate } from "@/lib/format";
import type { EscRow, Group } from "@/lib/types";

const STATUSES = ["open", "in_progress", "closed"];
const tone = (s: string) => (s === "closed" ? "good" : s === "in_progress" ? "warn" : "bad");
const bars = (g?: Group[]) => (g ?? []).map((x) => ({ id: x.id, name: x.name, values: { count: x.count } }));

export default function EscalationsPage() {
  const sum = useEscSummary();
  const f = useApiFilters();
  const patchF = useFilterStore((s) => s.patch);
  const { data: me } = useMe();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [edit, setEdit] = useState<EscRow | null>(null);

  const list = useQuery({
    queryKey: ["esc-list", f, page, status, search],
    queryFn: () => api<{ total: number; rows: EscRow[] }>("/escalations", { ...f, page, page_size: 10, action_status: status, search }),
    placeholderData: keepPreviousData,
  });
  const s = sum.data;
  const wide = useWide();
  const canEdit = me?.role === "manager" || me?.role === "admin";

  return (
    <>
      <PageHeader title="Escalations" subtitle="Client escalations, root causes and corrective / preventive action tracking">
        <Breadcrumbs />
      </PageHeader>
      {sum.isError && <QueryError error={sum.error} />}
      <KpiHero loading={sum.isLoading} wide={wide} items={[
        { key: "total", label: "Escalations", tone: "bad", hint: "Raised in period", color: "#b91c1c", value: s?.total },
        { key: "open", label: "Open", tone: "warn", hint: "Action not closed", color: "#c2410c", value: s?.open },
        { key: "closed", label: "Closed", tone: "good", hint: "Action closed", color: "#1f7a4d", value: s?.closed },
      ]} />

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <ChartCard title="By client" subtitle="Click a bar to filter">
          {sum.isLoading ? <ChartSkeleton h={200} /> : <RankBars rows={bars(s?.by_client)} keys={["count"]} onClick={(r) => r.id && patchF({ client_id: r.id })} />}
        </ChartCard>
        <ChartCard title="By project">
          {sum.isLoading ? <ChartSkeleton h={200} /> : <RankBars rows={bars(s?.by_project)} keys={["count"]} onClick={(r) => r.id && patchF({ project_id: r.id })} />}
        </ChartCard>
        <ChartCard title="By editor">
          {sum.isLoading ? <ChartSkeleton h={200} /> : <RankBars rows={bars(s?.by_editor)} keys={["count"]} onClick={(r) => r.id && patchF({ editor_id: r.id })} />}
        </ChartCard>
        <ChartCard title="Root causes" subtitle="Normalised text of the Root Cause column">
          {sum.isLoading ? <ChartSkeleton h={200} /> : <RankBars rows={bars(s?.by_root_cause)} keys={["count"]} />}
        </ChartCard>
        <ChartCard title="Error categories">
          {sum.isLoading ? <ChartSkeleton h={200} /> : <RankBars rows={bars(s?.by_error_category)} keys={["count"]} />}
        </ChartCard>
        <ChartCard title="Escalations by month">
          {sum.isLoading ? <ChartSkeleton h={200} /> : <RankBars rows={bars(s?.by_month)} keys={["count"]} limit={24} />}
        </ChartCard>
      </div>

      <ChartCard className="mt-4" title="Escalation log"
        action={
          <div className="flex flex-wrap items-end gap-2">
            <Input placeholder="Search…" aria-label="Search escalations" className="h-9 w-44" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
            <Select label="Action status" className="w-36" value={status} onChange={(v) => { setStatus(v); setPage(1); }} options={STATUSES.map((x) => ({ value: x, label: x.replace("_", " ") }))} />
          </div>
        }>
        <div className="overflow-auto rounded-xl border">
          <table className="w-full min-w-[56rem] text-left text-sm">
            <caption className="sr-only">Escalations</caption>
            <thead className="bg-muted/80"><tr>{["Date", "Client / project", "Job", "Editor", "Root cause", "Action", "Status", ""].map((h) => <th key={h} scope="col" className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {(list.data?.rows ?? []).map((r) => (
                <tr key={r.id} className="border-t align-top">
                  <td className="whitespace-nowrap px-3 py-2">{fmtDate(r.raised_date)}</td>
                  <td className="px-3 py-2">{r.project}<span className="block text-xs text-muted-foreground">{r.client}</span></td>
                  <td className="px-3 py-2 tabular">{r.job_id ?? "–"}</td>
                  <td className="px-3 py-2">{r.editor ?? "–"}</td>
                  <td className="max-w-xs px-3 py-2">{r.root_cause ?? "–"}</td>
                  <td className="max-w-xs px-3 py-2 text-muted-foreground">{r.corrective_action || r.preventive_action || "–"}</td>
                  <td className="px-3 py-2"><Badge tone={tone(r.action_status)}>{r.action_status.replace("_", " ")}</Badge></td>
                  <td className="px-3 py-2">{canEdit && <Button size="icon" variant="ghost" aria-label={`Update action for escalation ${r.id}`} onClick={() => setEdit(r)}><Pencil className="h-4 w-4" /></Button>}</td>
                </tr>
              ))}
              {(list.data?.rows.length ?? 0) === 0 && <tr><td colSpan={8} className="px-3 py-10 text-center text-muted-foreground">No escalations for these filters.</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} pageSize={10} total={list.data?.total ?? 0} onPage={setPage} />
      </ChartCard>
      {edit && <EditDialog row={edit} onClose={() => setEdit(null)} />}
    </>
  );
}

function EditDialog({ row, onClose }: { row: EscRow; onClose: () => void }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState(row.action_status);
  const [owner, setOwner] = useState(row.action_owner ?? "");
  const [corrective, setCorrective] = useState(row.corrective_action ?? "");
  const [preventive, setPreventive] = useState(row.preventive_action ?? "");
  const m = useMutation({
    mutationFn: () => apiPatch(`/escalations/${row.id}`, { action_status: status, action_owner: owner || null, corrective_action: corrective || null, preventive_action: preventive || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["esc-list"] }); qc.invalidateQueries({ queryKey: ["esc-sum"] }); onClose(); },
  });
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Escalation #${row.id}`} description={`${row.project} · job ${row.job_id ?? "n/a"}`}>
      <div className="space-y-3">
        <p className="rounded-xl bg-muted/60 p-3 text-sm">{row.client_feedback ?? "No client feedback recorded."}</p>
        <Select label="Status" value={status} onChange={setStatus} placeholder="Choose" options={STATUSES.map((x) => ({ value: x, label: x.replace("_", " ") }))} />
        <label className="block space-y-1 text-sm">Owner<Input value={owner} onChange={(e) => setOwner(e.target.value)} /></label>
        <label className="block space-y-1 text-sm">Corrective action<Input value={corrective} onChange={(e) => setCorrective(e.target.value)} /></label>
        <label className="block space-y-1 text-sm">Preventive action<Input value={preventive} onChange={(e) => setPreventive(e.target.value)} /></label>
        {m.isError && <QueryError error={m.error} />}
        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="brand" onClick={() => m.mutate()} disabled={m.isPending}>Save</Button>
        </div>
      </div>
    </Modal>
  );
}
