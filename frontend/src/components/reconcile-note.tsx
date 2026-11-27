import { fmtInt } from "@/lib/format";
import type { Reconcile } from "@/lib/types";

const forms = (n: number) => `${fmtInt(n)} form${n === 1 ? "" : "s"}`;

/** Explains the gap between Finalised (Transaction Date) and Received (Input Date); the highlighted rows below are the cause. */
export function ReconcileNote({ r }: { r: Reconcile }) {
  const diff = r.difference;
  const reasons: string[] = [];
  if (r.no_input_date) reasons.push(`${forms(r.no_input_date)} with no Input Date`);
  if (r.received_before) reasons.push(`${forms(r.received_before)} received before the period`);
  if (r.received_after) reasons.push(`${forms(r.received_after)} received after the period`);
  return (
    <div role="status" className="mb-3 rounded-xl border border-warn/50 bg-warn/10 p-3 text-sm">
      <p className="font-medium">
        Finalised <b className="tabular">{fmtInt(r.finalised)}</b> vs Received <b className="tabular">{fmtInt(r.received)}</b>
        {diff === 0 ? " – the two match for this period." : ` – difference ${diff > 0 ? "+" : ""}${fmtInt(diff)}.`}
      </p>
      <p className="mt-1 text-muted-foreground">
        Finalised counts the Transaction Date, Received counts the Input Date.{" "}
        {r.not_received > 0
          ? <>The <b>{forms(r.not_received)}</b> finalised here but not received in the period ({reasons.join(", ")}) are <b>highlighted and listed first</b>.</>
          : "Every finalised form was also received in the period."}
        {" "}{r.received_not_finalised > 0
          ? `${forms(r.received_not_finalised)} received in the period ${r.received_not_finalised === 1 ? "is" : "are"} not finalised in it (see Received).`
          : "No form received in the period is waiting to be finalised."}
      </p>
    </div>
  );
}
