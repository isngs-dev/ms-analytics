"use client";
import { useState } from "react";
import { MessageSquareWarning } from "lucide-react";
import { Card, Tabs } from "./ui/primitives";
import { ChartSkeleton, QueryError } from "./widgets";
import { useQuality } from "@/lib/hooks";
import { useDrill } from "@/lib/drill";
import { useFilterStore } from "@/lib/store";
import { fmtInt } from "@/lib/format";

const tone = (p: number | null) => (p == null ? "bg-muted" : p >= 95 ? "bg-good" : p >= 85 ? "bg-warn" : "bg-bad");

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

/** How many reports were edited in the selected period and how many of them came back from the client. */
export function QualityCard() {
  const [by, setBy] = useState<"client" | "project">("client");
  const q = useQuality(by);
  const show = useDrill((s) => s.show);
  const patch = useFilterStore((s) => s.patch);
  const o = q.data?.overall;
  const p = o?.quality_pct;
  const rows = q.data?.rows ?? [];

  return (
    <Card className="mt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <MessageSquareWarning className="h-4 w-4 text-primary" /> Edited reports &amp; client feedback quality
          </h2>
          <p className="max-w-3xl text-xs text-muted-foreground">
            {q.data?.definition ?? "Share of edited reports that did not come back from the client."}
          </p>
        </div>
        <Tabs label="Break down by" value={by} onChange={setBy} items={[{ value: "client", label: "By client" }, { value: "project", label: "By project" }]} />
      </div>

      {q.isError ? <QueryError error={q.error} /> : q.isLoading ? <ChartSkeleton h={220} /> : (
        <div className="grid gap-4 xl:grid-cols-[22rem_1fr]">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Reports edited" value={fmtInt(o!.edited)}
              hint={`all outcomes · ${fmtInt(o!.marked_edited)} marked "Edited & Saved"`}
              onClick={() => show({ metric: "processed", title: "Reports edited (all outcomes)" })} />
            <Stat label="Feedback quality" value={p == null ? "–" : `${p.toFixed(1)}%`} hint={`${fmtInt(o!.clean)} went through clean`} />
            <Stat label="Client escalations" value={fmtInt(o!.escalated)} hint={o!.escalation_free_pct == null ? undefined : `${o!.escalation_free_pct.toFixed(1)}% escalation-free`} />
          </div>

          <div className="max-h-80 overflow-auto rounded-xl border">
            <table className="w-full min-w-[28rem] text-left text-sm">
              <caption className="sr-only">Feedback quality by {by}</caption>
              <thead className="sticky top-0 bg-muted/90 backdrop-blur"><tr>
                <th scope="col" className="px-3 py-2 font-medium capitalize">{by}</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Edited</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Escalated</th>
                <th scope="col" className="w-48 px-3 py-2 font-medium">Quality</th>
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t hover:bg-muted/40">
                    <th scope="row" className="px-3 py-2 text-left font-medium">
                      <button className="text-primary hover:underline"
                        onClick={() => patch(by === "client" ? { client_id: r.id, project_id: undefined } : { project_id: r.id })}>{r.name}</button>
                      {r.parent && <span className="block text-xs font-normal text-muted-foreground">{r.parent}</span>}
                    </th>
                    <td className="px-3 py-2 text-right tabular">{fmtInt(r.edited)}</td>
                    <td className="px-3 py-2 text-right tabular">{fmtInt(r.escalated)}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden>
                          <div className={`h-full rounded-full ${tone(r.quality_pct)}`} style={{ width: `${r.quality_pct ?? 0}%` }} />
                        </div>
                        <span className="w-12 text-right tabular">{r.quality_pct == null ? "–" : `${r.quality_pct.toFixed(1)}%`}</span>
                      </div>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">No edited reports in this period</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
