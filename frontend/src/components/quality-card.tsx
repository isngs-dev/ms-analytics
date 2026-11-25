"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { MessageSquareWarning } from "lucide-react";
import { Card, Tabs } from "./ui/primitives";
import { ChartSkeleton, QueryError } from "./widgets";
import { useQuality } from "@/lib/hooks";
import { useDrill } from "@/lib/drill";
import { useFilterStore } from "@/lib/store";
import { hrefWith, withPeriodPatch } from "@/lib/filters";
import { fmtInt } from "@/lib/format";

const pctText = (p: number | null | undefined, d = 1) => (p == null ? "–" : `${p.toFixed(d)}%`);
const barTone = (p: number | null) => (p == null ? "bg-muted" : p >= 80 ? "bg-good" : p >= 40 ? "bg-warn" : "bg-bad");

function Stat({ label, value, hint, onClick }: { label: string; value: string; hint?: string; onClick?: () => void }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag onClick={onClick} className={`rounded-xl border bg-card/50 p-3 text-left ${onClick ? "hover:border-primary" : ""}`}>
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </Tag>
  );
}

const QC_DEFINITION =
  "Quality checked = of the reports in projects that have a QC step, the share with a QC Date by the period end. "
  + "Client escalations = the escalations on the Escalations page for the same filters (raised in the period). "
  + "Escalation-free = reports without a client escalation.";

/** Big gauge: the share of reports that went through quality check. */
function Gauge({ pct, done, scope }: { pct: number | null | undefined; done: number; scope: number }) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  return (
    <div className="flex items-center gap-4 rounded-xl border bg-card/50 p-4">
      <div role="img" aria-label={`Quality checked ${pctText(pct)}`} className="grid h-28 w-28 shrink-0 place-items-center rounded-full"
        style={{ background: `conic-gradient(hsl(var(--primary)) ${p * 3.6}deg, hsl(var(--muted)) 0)` }}>
        <div className="grid h-20 w-20 place-items-center rounded-full bg-card text-center">
          <span className="text-xl font-semibold tabular">{pctText(pct)}</span>
        </div>
      </div>
      <div className="min-w-0">
        <p className="text-xs uppercase tracking-wider text-muted-foreground">Quality checked</p>
        <p className="mt-1 text-sm"><b className="tabular">{fmtInt(done)}</b> of <b className="tabular">{fmtInt(scope)}</b> reports have been through QC</p>
        <p className="mt-1 text-xs text-muted-foreground">Only projects that have a QC step are counted.</p>
      </div>
    </div>
  );
}

/** What share of the reports was quality-checked (QC), and how many came back as client escalations. */
export function QualityCard() {
  const [by, setBy] = useState<"client" | "project">("client");
  const q = useQuality(by);
  const show = useDrill((s) => s.show);
  const router = useRouter();
  const patch = useFilterStore((s) => s.patch);
  const filters = useFilterStore((s) => s.filters);
  const o = q.data?.overall;
  const rows = q.data?.rows ?? [];

  return (
    <Card className="mt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <MessageSquareWarning className="h-4 w-4 text-primary" /> Quality check (QC) &amp; client escalations
          </h2>
          <p className="max-w-3xl text-xs text-muted-foreground">
            {QC_DEFINITION} Follows every filter above, so pick a client to see its own quality check.
          </p>
        </div>
        <Tabs label="Break down by" value={by} onChange={setBy} items={[{ value: "client", label: "By client" }, { value: "project", label: "By project" }]} />
      </div>

      {q.isError ? <QueryError error={q.error} /> : q.isLoading ? <ChartSkeleton h={220} /> : (
        <div className="grid gap-4 xl:grid-cols-[26rem_1fr]">
          <div className="space-y-3">
            <Gauge pct={o!.qc_checked_pct} done={o!.qc_done} scope={o!.qc_scope} />
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Waiting for QC" value={fmtInt(o!.qc_pending)} hint="QC step exists, not checked yet" />
              <Stat label="Client escalations" value={fmtInt(o!.escalated)} onClick={() => router.push(hrefWith("/escalations", filters))}
                hint="raised in the period · click to open exactly these" />
              <Stat label="Escalation-free" value={pctText(o!.escalation_free_pct, 2)} hint={`${fmtInt(o!.clean)} reports without a client escalation`} />
            </div>
          </div>

          <div className="max-h-[28rem] overflow-auto rounded-xl border">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <caption className="sr-only">Quality check and escalations by {by}</caption>
              <thead className="sticky top-0 bg-muted/90 backdrop-blur"><tr>
                <th scope="col" className="px-3 py-2 font-medium capitalize">{by}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">QC done</th>
                <th scope="col" className="w-52 px-3 py-2 font-medium">Quality checked</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Escalations</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Escalation-free</th>
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t hover:bg-muted/40">
                    <th scope="row" className="px-3 py-2 text-left font-medium">
                      <button className="text-primary hover:underline"
                        onClick={() => patch(by === "client" ? { client_id: r.id, project_id: undefined } : { project_id: r.id })}>{r.name}</button>
                      {r.parent && <span className="block text-xs font-normal text-muted-foreground">{r.parent}</span>}
                    </th>
                    <td className="px-3 py-2 text-right tabular">{r.qc_scope ? <>{fmtInt(r.qc_done)}<span className="text-xs text-muted-foreground"> / {fmtInt(r.qc_scope)}</span></> : "–"}</td>
                    <td className="px-3 py-2">
                      {r.qc_checked_pct == null ? <span className="text-xs text-muted-foreground">{r.edited ? "no QC step" : "–"}</span> : (
                        <div className="flex items-center gap-2">
                          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden>
                            <div className={`h-full rounded-full ${barTone(r.qc_checked_pct)}`} style={{ width: `${Math.max(r.qc_checked_pct, 1.5)}%` }} />
                          </div>
                          <span className="w-14 text-right tabular">{pctText(r.qc_checked_pct)}</span>
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular">
                      {r.escalated > 0 ? (
                        <button className="text-primary hover:underline" aria-label={`Open the ${r.escalated} escalations of ${r.name}`}
                          onClick={() => router.push(hrefWith("/escalations", withPeriodPatch(filters, by === "client" ? { client_id: r.id, project_id: undefined } : { project_id: r.id })))}>
                          {fmtInt(r.escalated)}
                        </button>
                      ) : fmtInt(r.escalated)}
                    </td>
                    <td className="px-3 py-2 text-right tabular">{pctText(r.escalation_free_pct, 2)}</td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">No reports in this period</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
