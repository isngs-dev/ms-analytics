"use client";
import { useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ExternalLink, FileSpreadsheet } from "lucide-react";
import { Badge, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/dialog";
import { Pager } from "@/components/data-table";
import { ChartCard, KpiCard, PageHeader, QueryError } from "@/components/widgets";
import { api } from "@/lib/api";
import { fmtDate, fmtInt } from "@/lib/format";
import type { CoverageResp, DocDetail, DocRow, DocsResp, TabRowsResp } from "@/lib/types";

const statusTone = (s: string) => (s === "active" ? "good" : s === "error" ? "bad" : "warn");
const sevTone = (s: string) => (s === "error" ? "bad" : s === "warn" ? "warn" : "neutral");

export default function DocumentsPage() {
  const [search, setSearch] = useState("");
  const [year, setYear] = useState("");
  const [quarter, setQuarter] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("name");
  const [order, setOrder] = useState("asc");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const reset = (fn: (v: string) => void) => (v: string) => { fn(v); setPage(1); };

  const facets = useQuery({ queryKey: ["doc-facets"], queryFn: () => api<{ years: number[]; statuses: string[] }>("/documents/facets"), staleTime: 60_000 });
  const q = useQuery({
    queryKey: ["documents", search, year, quarter, status, sort, order, page],
    queryFn: () => api<DocsResp>("/documents", { search, year, quarter, status, sort, order, page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const toggleSort = (k: string) => { if (sort === k) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(k); setOrder(k === "name" ? "asc" : "desc"); } };
  const rows = q.data?.rows ?? [];

  return (
    <>
      <PageHeader title="Drive documents" subtitle="Every workbook found in the Drive folder, what was read from each tab, and how every row is accounted for" />
      {q.isError && <QueryError error={q.error} />}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Documents" value={q.data?.total} loading={q.isLoading} />
        <KpiCard label="Forms loaded" value={q.data?.totals.forms} loading={q.isLoading} tone="good" />
        <KpiCard label="Escalations" value={q.data?.totals.escalations} loading={q.isLoading} tone="bad" />
      </div>

      <CoverageCard />

      <ChartCard className="mt-4" title="Workbooks"
        subtitle="Click a row for its tabs, reconciliation and issues. Totals follow the filters here, not the dashboard filters"
        action={
          <div className="flex flex-wrap items-end gap-2">
            <Input placeholder="Search name…" aria-label="Search documents" className="h-9 w-48" value={search} onChange={(e) => reset(setSearch)(e.target.value)} />
            <Select label="Year" className="w-24" value={year} onChange={reset(setYear)} options={(facets.data?.years ?? []).map((y) => ({ value: y, label: String(y) }))} />
            <Select label="Quarter" className="w-24" value={quarter} onChange={reset(setQuarter)} options={[1, 2, 3, 4].map((n) => ({ value: n, label: `Q${n}` }))} />
            <Select label="Status" className="w-28" value={status} onChange={reset(setStatus)} options={(facets.data?.statuses ?? []).map((s) => ({ value: s, label: s }))} />
          </div>
        }>
        <div className="overflow-auto rounded-xl border">
          <table className="w-full min-w-[70rem] text-left text-sm">
            <caption className="sr-only">Drive documents</caption>
            <thead className="bg-muted/80">
              <tr>
                {[["name", "Document"], [null, "Client / project"], [null, "Period"], [null, "Status"], ["modified", "Changed in Drive"], ["synced", "Last read"],
                  [null, "Tabs read"], ["forms", "Forms"], [null, "Esc."], [null, "Rows rejected"], ["issues", "Issues"]].map(([k, h]) => (
                  <th key={h as string} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">
                    {k ? <button onClick={() => toggleSort(k as string)} className="hover:text-primary">{h}{sort === k ? (order === "asc" ? " ↑" : " ↓") : ""}</button> : h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r: DocRow) => (
                <tr key={r.id} tabIndex={0} onClick={() => setOpen(r.id)} onKeyDown={(e) => e.key === "Enter" && setOpen(r.id)}
                  className="cursor-pointer border-t hover:bg-muted/50">
                  <th scope="row" className="max-w-[22rem] px-3 py-2 text-left font-medium">
                    <span className="flex items-center gap-2"><FileSpreadsheet className="h-4 w-4 shrink-0 text-primary" aria-hidden /><span className="truncate" title={r.name}>{r.name}</span></span>
                  </th>
                  <td className="px-3 py-2">{r.client ?? "–"}<span className="block text-xs text-muted-foreground">{r.project ?? ""}</span></td>
                  <td className="whitespace-nowrap px-3 py-2">{r.year ? `${r.year} Q${r.quarter ?? "?"}` : "–"}</td>
                  <td className="px-3 py-2"><Badge tone={statusTone(r.status)}>{r.status}</Badge></td>
                  <td className="whitespace-nowrap px-3 py-2">{fmtDate(r.modified_time)}</td>
                  <td className="whitespace-nowrap px-3 py-2">{fmtDate(r.last_synced_at)}</td>
                  <td className="px-3 py-2 tabular">{r.tabs_read}<span className="text-muted-foreground"> / {r.tabs}</span></td>
                  <td className="px-3 py-2 tabular">{fmtInt(r.forms)}</td>
                  <td className="px-3 py-2 tabular">{fmtInt(r.escalations)}</td>
                  <td className="px-3 py-2 tabular">{r.rows_rejected ? <Badge tone="bad">{fmtInt(r.rows_rejected)}</Badge> : "0"}</td>
                  <td className="px-3 py-2 tabular">{r.issues ? <Badge tone="warn">{fmtInt(r.issues)}</Badge> : "0"}</td>
                </tr>
              ))}
              {rows.length === 0 && !q.isLoading && <tr><td colSpan={12} className="px-3 py-10 text-center text-muted-foreground">No documents match.</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} pageSize={25} total={q.data?.total ?? 0} onPage={setPage} />
      </ChartCard>
      {open != null && <DocDialog id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

const KIND_LABEL: Record<string, string> = {
  operational: "Form tabs (month tabs)", rework: "Rework tabs (kept, not counted in any analytics)", escalation: "Escalation / client-feedback tabs",
  supplementary: "Form-like extra tabs (Incomplete, Detail, Copy of …)", reference: "Other tabs, kept as written",
  master: "Master lists", ignored: "Never read (credentials)",
};

/** Proof that nothing is skipped: every tab of every workbook, by what happened to it. */
function CoverageCard() {
  const q = useQuery({ queryKey: ["doc-coverage"], queryFn: () => api<CoverageResp>("/documents/coverage"), staleTime: 60_000 });
  const c = q.data;
  return (
    <ChartCard className="mt-4" title="Coverage: every tab of every workbook"
      subtitle="All tabs are read except the ones that hold passwords. Form-like tabs add the Job IDs the month tabs lack, and every other tab is kept row by row (open a document, then 'View rows').">
      {q.isError ? <QueryError error={q.error} /> : !c ? <p className="py-6 text-center text-sm text-muted-foreground">Loading…</p> : (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <dl className="grid grid-cols-2 gap-3 text-sm lg:grid-cols-1">
            {[["Workbooks", fmtInt(c.files)], ["Tabs in them", fmtInt(c.tabs)], ["Rows kept from other tabs", fmtInt(c.raw_rows_stored)], ["Forms added by extra tabs", fmtInt(c.forms_from_supplementary_tabs)]].map(([k, v]) => (
              <div key={k} className="rounded-xl border bg-card/50 p-3"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="mt-1 text-xl font-semibold tabular">{v}</dd></div>
            ))}
          </dl>
          <div className="overflow-auto rounded-xl border">
            <table className="w-full min-w-[34rem] text-left text-sm">
              <caption className="sr-only">Tabs by what happened to them</caption>
              <thead className="bg-muted/80"><tr>{["What the tab is", "Tabs", "Rows in sheets", "Rows loaded / kept"].map((h) => <th key={h} scope="col" className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {c.kinds.map((k) => (
                  <tr key={k.kind} className="border-t">
                    <th scope="row" className="px-3 py-2 text-left font-medium">{KIND_LABEL[k.kind] ?? k.kind}<span className="block text-xs font-normal text-muted-foreground">{k.note}</span></th>
                    <td className="px-3 py-2 tabular">{fmtInt(k.tabs)}</td>
                    <td className="px-3 py-2 tabular">{k.kind === "ignored" ? "–" : fmtInt(k.rows_seen)}</td>
                    <td className="px-3 py-2 tabular">{k.kind === "ignored" ? "–" : fmtInt(k.rows_loaded)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </ChartCard>
  );
}

/** The rows of a tab that is not part of the analytics tables, exactly as written in the sheet. */
function TabRowsDialog({ docId, tab, onClose }: { docId: number; tab: { id: number; tab: string }; onClose: () => void }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const q = useQuery({
    queryKey: ["tab-rows", docId, tab.id, page, search],
    queryFn: () => api<TabRowsResp>(`/documents/${docId}/tabs/${tab.id}/rows`, { page, page_size: 50, search }),
    placeholderData: keepPreviousData,
  });
  const d = q.data;
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Tab: ${tab.tab}`} wide
      description={d ? `${fmtInt(d.total)} rows kept exactly as written in the sheet` : "Loading…"}>
      <Input placeholder="Search this tab…" aria-label="Search rows" className="mb-3 max-w-xs" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
      {q.isError ? <QueryError error={q.error} /> : (
        <>
          <div className="max-h-[60vh] overflow-auto rounded-xl border">
            <table className="w-full min-w-max text-left text-sm">
              <thead className="sticky top-0 bg-muted/90 backdrop-blur">
                <tr><th scope="col" className="px-3 py-2 font-medium text-muted-foreground">Row</th>
                  {(d?.header ?? []).map((h, i) => <th key={i} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">{h || `Column ${i + 1}`}</th>)}</tr>
              </thead>
              <tbody>
                {(d?.rows ?? []).map((r) => (
                  <tr key={r.row_no} className="border-t align-top">
                    <td className="px-3 py-1.5 tabular text-muted-foreground">{r.row_no}</td>
                    {r.cells.map((c, i) => <td key={i} className="max-w-[28rem] px-3 py-1.5"><span className="line-clamp-3 whitespace-pre-line" title={c}>{c || <span className="text-muted-foreground">–</span>}</span></td>)}
                  </tr>
                ))}
                {d && d.rows.length === 0 && <tr><td colSpan={(d.header.length || 1) + 1} className="px-3 py-8 text-center text-muted-foreground">No rows match.</td></tr>}
              </tbody>
            </table>
          </div>
          <Pager page={page} pageSize={50} total={d?.total ?? 0} onPage={setPage} />
        </>
      )}
    </Modal>
  );
}

function DocDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["document", id], queryFn: () => api<DocDetail>(`/documents/${id}`) });
  const [viewTab, setViewTab] = useState<{ id: number; tab: string } | null>(null);
  const d = q.data;
  const s = d?.summary;
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={d?.name ?? "Document"} wide
      description={d ? `${d.client ?? "?"} · ${d.year ?? ""} Q${d.quarter ?? "?"} · changed in Drive ${fmtDate(d.modified_time)} · last read ${fmtDate(d.last_synced_at)}` : "Loading…"}>
      {q.isError ? <QueryError error={q.error} /> : !d ? <p className="py-10 text-center text-muted-foreground">Loading…</p> : (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            <a href={d.drive_url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1 rounded-xl border bg-card/60 px-3 text-sm hover:bg-muted">
              Open in Google Drive <ExternalLink className="h-3.5 w-3.5" />
            </a>
            <Link href={`/explorer?search=${encodeURIComponent(d.name)}`} onClick={onClose} className="inline-flex h-9 items-center rounded-xl border bg-card/60 px-3 text-sm hover:bg-muted">
              See every record from this document
            </Link>
          </div>

          <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            {[["Forms", fmtInt(s!.forms)], ["Received", `${fmtDate(s!.first_received)} – ${fmtDate(s!.last_received)}`], ["Editors", fmtInt(s!.editors)], ["Projects", fmtInt(s!.projects)],
              ["Processed (have an edit date)", fmtInt(s!.processed)], ["With QC date", fmtInt(s!.with_qc)], ["Repeat Job IDs merged", fmtInt(s!.duplicates)], ["Status", d.status]].map(([k, v]) => (
              <div key={k} className="rounded-xl border bg-card/50 p-3"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="mt-1 font-semibold tabular">{v}</dd></div>
            ))}
          </dl>

          <section>
            <h3 className="mb-1 text-sm font-semibold">Tabs and row reconciliation</h3>
            <p className="mb-2 text-xs text-muted-foreground">Every data row in a read tab is accounted for: blank/template rows + loaded rows + rejected rows = rows below the header. Only credential tabs are never fetched; every other tab is either loaded into the analytics or kept row by row (use "View rows").</p>
            <div className="overflow-auto rounded-xl border">
              <table className="w-full min-w-[46rem] text-left text-sm">
                <thead className="bg-muted/80"><tr>{["Tab", "Kind", "Rows in sheet", "Blank / template", "Loaded", "Rejected", "Repeat IDs", "Forms", "Esc."].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr></thead>
                <tbody>
                  {d.tabs.map((t) => {
                    const read = t.kind !== "ignored";
                    return (
                      <tr key={t.id} className="border-t">
                        <th scope="row" className="px-3 py-2 text-left font-medium">{t.tab}</th>
                        <td className="px-3 py-2"><Badge tone={read ? "good" : "neutral"}>{t.kind}</Badge>{t.note && <span className="ml-2 text-xs text-muted-foreground">{t.note}</span>}
                          {t.browsable && <button className="ml-2 text-xs text-primary hover:underline" onClick={() => setViewTab({ id: t.id, tab: t.tab })}>View rows</button>}</td>
                        <td className="px-3 py-2 tabular">{read ? fmtInt(Math.max(0, t.rows_seen - (t.header_row ?? 0))) : "–"}</td>
                        <td className="px-3 py-2 tabular">{read ? fmtInt(t.rows_placeholder) : "–"}</td>
                        <td className="px-3 py-2 tabular">{read ? fmtInt(t.rows_loaded) : "–"}</td>
                        <td className="px-3 py-2 tabular">{read && t.rows_rejected ? <Badge tone="bad">{fmtInt(t.rows_rejected)}</Badge> : read ? "0" : "–"}</td>
                        <td className="px-3 py-2 tabular">{read ? fmtInt(t.rows_duplicate) : "–"}</td>
                        <td className="px-3 py-2 tabular">{fmtInt(t.forms)}</td>
                        <td className="px-3 py-2 tabular">{fmtInt(t.escalations)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            <section>
              <h3 className="mb-1 text-sm font-semibold">Ops Status in this document</h3>
              <ul className="space-y-1 text-sm">{d.ops_statuses.map((x) => <li key={x.status} className="flex justify-between border-b py-1"><span>{x.status}</span><span className="tabular">{fmtInt(x.count)}</span></li>)}</ul>
            </section>
            <section>
              <h3 className="mb-1 text-sm font-semibold">Projects</h3>
              <ul className="space-y-1 text-sm">{d.projects.map((x) => <li key={x.project} className="flex justify-between border-b py-1"><span>{x.project}</span><span className="tabular">{fmtInt(x.forms)}</span></li>)}</ul>
            </section>
          </div>

          <section>
            <h3 className="mb-1 text-sm font-semibold">Issues from the last read</h3>
            {d.issue_types.length === 0 ? <p className="text-sm text-muted-foreground">No issues.</p> : (
              <>
                <div className="mb-2 flex flex-wrap gap-2">{d.issue_types.map((i) => <Badge key={i.type + i.severity} tone={sevTone(i.severity) as "bad" | "warn" | "neutral"}>{i.type} · {fmtInt(i.count)}</Badge>)}</div>
                <ul className="max-h-48 space-y-1 overflow-auto text-xs text-muted-foreground">
                  {d.issues.map((i, k) => <li key={k}><strong className="text-foreground">{i.tab ?? "file"}{i.row_no ? ` row ${i.row_no}` : ""}</strong> · {i.type}: {i.detail}</li>)}
                </ul>
              </>
            )}
          </section>
        </div>
      )}
      {viewTab && <TabRowsDialog docId={id} tab={viewTab} onClose={() => setViewTab(null)} />}
    </Modal>
  );
}
