"use client";
import { fmtInt, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BreakRow } from "@/lib/types";

const COLS: { key: keyof BreakRow; label: string }[] = [
  { key: "received", label: "Received" },
  { key: "finalised", label: "Finalised" },
  { key: "qc_completed", label: "QC done" },
  { key: "qc_pending", label: "QC pending" },
];

/** Per-level table (client / project / editor …) with a completion bar. Rows are keyboard-activatable. */
export function MetricTable({
  rows, firstLabel, onRow, showParent, caption,
}: { rows: BreakRow[]; firstLabel: string; onRow?: (r: BreakRow) => void; showParent?: boolean; caption: string }) {
  return (
    <div className="overflow-auto rounded-xl border">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-muted/80">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">{firstLabel}</th>
            {COLS.map((c) => <th key={c.key} scope="col" className="px-3 py-2 text-right font-medium">{c.label}</th>)}
            <th scope="col" className="px-3 py-2 font-medium">Completion</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={`${r.id}-${i}`}
              tabIndex={onRow ? 0 : undefined}
              onClick={onRow ? () => onRow(r) : undefined}
              onKeyDown={onRow ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onRow(r)) : undefined}
              className={cn("border-t", onRow && "cursor-pointer hover:bg-muted/50")}
            >
              <th scope="row" className="px-3 py-2 font-medium">
                {r.name}{showParent && r.parent ? <span className="ml-2 text-xs font-normal text-muted-foreground">{r.parent}</span> : null}
              </th>
              {COLS.map((c) => <td key={c.key} className="px-3 py-2 text-right tabular">{fmtInt(r[c.key] as number)}</td>)}
              <td className="min-w-[9rem] px-3 py-2">
                <div className="flex items-center gap-2">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted" role="img" aria-label={`Completion ${fmtPct(r.completion_pct)}`}>
                    <div className="bg-brand h-full" style={{ width: `${Math.min(100, r.completion_pct ?? 0)}%` }} />
                  </div>
                  <span className="w-12 text-right text-xs tabular text-muted-foreground">{fmtPct(r.completion_pct, 0)}</span>
                </div>
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={8} className="px-3 py-10 text-center text-muted-foreground">No data for these filters.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
