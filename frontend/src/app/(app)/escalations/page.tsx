"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { Badge, Button, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/dialog";
import { Pager } from "@/components/data-table";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ChartCard, ChartSkeleton, KpiCard, PageHeader, QueryError } from "@/components/widgets";
import { RankBars } from "@/components/charts";
import { api, patch as apiPatch } from "@/lib/api";
import { useApiFilters, useEscSummary, useMe } from "@/lib/hooks";
import { useFilterStore } from "@/lib/store";
import { fmtDate } from "@/lib/format";
import type { EscRow, Group } from "@/lib/types";

const STATUSES = ["open", "in_progress", "closed"];
const tone = (s: string) => (s === "closed" ? "good" : s === "in_progress" ? "warn" : "bad");
const bars = (g?: Group[]) => (g ?? []).map((x) => ({ id: x.id, name: x.name, values: { count: x.count } }));

type Kind = "client" | "internal";

const BOX: Record<Kind, { title: string; blurb: string; empty: string; said: string }> = {
  client: {
    title: "Client escalations",
    blurb: "Raised by the client: every escalation whose error category is not QCD",
    empty: "No client escalations",
    said: "What the client said",
  },
  internal: {
    title: "Internal escalations (QCD)",
    blurb: "Caught by our own QC: escalations whose error category is QCD. They are never counted as client escalations",
    empty: "No internal escalations",
    said: "What was noted",
  },
};

export default function EscalationsPage() {
  const sum = useEscSummary("client");
  return (
    <>
      <PageHeader title="Escalations"
        subtitle={sum.data ? `${fmtDate(sum.data.period.from)} – ${fmtDate(sum.data.period.to)} · follows the filters above · client and internal escalations are kept apart` : "Client and internal escalations, root causes and corrective / preventive action tracking"}>
        <Breadcrumbs />
      </PageHeader>
      <EscalationBox kind="client" />
      <EscalationBox kind="internal" />
    </>
  );
}

/** One self-contained box (its own figures, charts and log) for either client or internal (QCD) escalations. */
function EscalationBox({ kind }: { kind: Kind }) {
  const t = BOX[kind];
  const sum = useEscSummary(kind);
  const f = useApiFilters();
  const patchF = useFilterStore((s) => s.patch);
  const { data: me } = useMe();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [edit, setEdit] = useState<EscRow | null>(null);

  const list = useQuery({
    queryKey: ["esc-list", kind, f, page, status, search],
    queryFn: () => api<{ total: number; rows: EscRow[] }>("/escalations", { ...f, kind, page, page_size: 10, action_status: status, search }),
    placeholderData: keepPreviousData,
  });
  const s = sum.data;
  const canEdit = me?.role === "manager" || me?.role === "admin";

  return (
    <section aria-label={t.title} className="mt-6 rounded-2xl border bg-card/30 p-4 sm:p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">{t.title}</h2>
        <p className="text-sm text-muted-foreground">{t.blurb}</p>
      </div>
      {sum.isError && <QueryError error={sum.error} />}
      <section aria-label={`${t.title} figures`} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <KpiCard label={t.title} tone={kind === "client" ? "bad" : "warn"} hint="Raised in period" loading={sum.isLoading} value={s?.total} />
        <KpiCard label="Open" tone="warn" hint="Action not closed" loading={sum.isLoading} value={s?.open} />
        <KpiCard label="Closed" tone="good" hint="Action closed" loading={sum.isLoading} value={s?.closed} />
      </section>

      {s && s.total === 0 && (
        <p role="status" className="mt-4 rounded-xl border bg-card/50 p-4 text-sm text-muted-foreground">
          {t.empty} between {fmtDate(s.period.from)} and {fmtDate(s.period.to)} for the selected filters.
          Only escalations whose date falls in this range are shown; widen the dates or clear a filter to see more.
        </p>
      )}

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
        {kind === "client" && (
          <ChartCard title="Error categories">
            {sum.isLoading ? <ChartSkeleton h={200} /> : <RankBars rows={bars(s?.by_error_category)} keys={["count"]} />}
          </ChartCard>
        )}
        <ChartCard title="By month">
          {sum.isLoading ? <ChartSkeleton h={200} /> : <RankBars rows={bars(s?.by_month)} keys={["count"]} limit={24} />}
        </ChartCard>
      </div>

      <ChartCard className="mt-4" title={t.said}
        subtitle={s ? `Most repeated first · ${s.with_client_escalation} of ${s.total} carry a note` : "Most repeated first"}>
        {sum.isLoading ? <ChartSkeleton h={240} /> : (s?.by_client_escalation.length ?? 0) === 0
          ? <p className="py-10 text-center text-sm text-muted-foreground">No notes for these filters.</p>
          : <RankBars rows={bars((s?.by_client_escalation ?? []).map((x) => ({ ...x, name: x.name.length > 90 ? `${x.name.slice(0, 88)}…` : x.name })))}
              keys={["count"]} limit={15} />}
      </ChartCard>

      <ChartCard className="mt-4" title={`${t.title} log`}
        action={
          <div className="flex flex-wrap items-end gap-2">
            <Input placeholder="Search…" aria-label={`Search ${t.title.toLowerCase()}`} className="h-9 w-44" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
            <Select label="Action status" className="w-36" value={status} onChange={(v) => { setStatus(v); setPage(1); }} options={STATUSES.map((x) => ({ value: x, label: x.replace("_", " ") }))} />
          </div>
        }>
        <div className="overflow-auto rounded-xl border">
          <table className="w-full min-w-[72rem] text-left text-sm">
            <caption className="sr-only">{t.title}</caption>
            <thead className="bg-muted/80"><tr>{["Date", "Client / project", "Job", "Editor", kind === "client" ? "Client escalation" : "Note", "Error category", "Root cause", "Action", "Status", ""].map((h, i) => <th key={i} scope="col" className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {(list.data?.rows ?? []).map((r) => (
                <tr key={r.id} className="border-t align-top">
                  <td className="whitespace-nowrap px-3 py-2">{fmtDate(r.raised_date)}</td>
                  <td className="px-3 py-2">{r.project}<span className="block text-xs text-muted-foreground">{r.client}</span></td>
                  <td className="px-3 py-2 tabular">{r.job_id ?? "–"}</td>
                  <td className="px-3 py-2">{r.editor ?? "–"}</td>
                  <td className="max-w-xs px-3 py-2">{r.client_feedback ?? "–"}</td>
                  <td className="px-3 py-2">{r.error_category ?? "–"}</td>
                  <td className="max-w-xs px-3 py-2">{r.root_cause ?? "–"}</td>
                  <td className="max-w-xs px-3 py-2 text-muted-foreground">{r.corrective_action || r.preventive_action || "–"}</td>
                  <td className="px-3 py-2"><Badge tone={tone(r.action_status)}>{r.action_status.replace("_", " ")}</Badge></td>
                  <td className="px-3 py-2">{canEdit && <Button size="icon" variant="ghost" aria-label={`Update action for escalation ${r.id}`} onClick={() => setEdit(r)}><Pencil className="h-4 w-4" /></Button>}</td>
                </tr>
              ))}
              {(list.data?.rows.length ?? 0) === 0 && <tr><td colSpan={10} className="px-3 py-10 text-center text-muted-foreground">{t.empty} for these filters.</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} pageSize={10} total={list.data?.total ?? 0} onPage={setPage} />
      </ChartCard>
      {edit && <EditDialog row={edit} onClose={() => setEdit(null)} />}
    </section>
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
