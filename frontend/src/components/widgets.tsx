"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, AlertCircle } from "lucide-react";
import { Badge, Card, Skeleton } from "./ui/primitives";
import { fmtInt, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Change } from "@/lib/types";

/** Mouse tilt for 3D-looking cards: leans toward the pointer, flattens on leave. No-op on touch. */
export function useTilt(max = 7) {
  return {
    onMouseMove: (e: React.MouseEvent<HTMLElement>) => {
      const el = e.currentTarget, r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
      el.style.setProperty("--ry", `${(px * max * 2).toFixed(2)}deg`);
      el.style.setProperty("--rx", `${(-py * max * 2).toFixed(2)}deg`);
    },
    onMouseLeave: (e: React.MouseEvent<HTMLElement>) => {
      e.currentTarget.style.setProperty("--ry", "0deg");
      e.currentTarget.style.setProperty("--rx", "0deg");
    },
  };
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight"><span className="text-gradient">{title}</span></h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

/** Count-up that respects prefers-reduced-motion. */
export function useCountUp(target: number, ms = 700) {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || from.current === target) { setV(target); from.current = target; return; }
    const start = performance.now(), a = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms);
      setV(a + (target - a) * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick); else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

export type Tone = "brand" | "good" | "warn" | "bad" | "neutral";
const toneBar: Record<Tone, string> = {
  brand: "from-[hsl(143_70%_76%)] to-[hsl(146_55%_46%)]", good: "from-primary to-good", warn: "from-warn to-bad", bad: "from-bad to-accent", neutral: "from-muted-foreground to-muted-foreground",
};

export function KpiCard({
  label, value, hint, tone = "brand", onClick, loading, suffix,
}: { label: string; value?: number | null; hint?: string; tone?: Tone; onClick?: () => void; loading?: boolean; suffix?: string }) {
  const shown = useCountUp(value ?? 0);
  const tilt = useTilt();
  const body = (
    <>
      <div className={cn("absolute inset-x-0 top-0 h-1 bg-gradient-to-r", toneBar[tone])} aria-hidden />
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      {loading && value == null ? <Skeleton className="mt-3 h-9 w-24" /> : (
        <p className="mt-2 text-3xl font-semibold tabular">{value == null ? "–" : fmtInt(shown)}{suffix}</p>
      )}
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </>
  );
  const cls = "glass tilt-3d relative overflow-hidden p-4 text-left";
  return onClick ? (
    <button onClick={onClick} {...tilt} className={cls} aria-label={`${label}: ${value ?? "no data"}. Show records`}>
      {body}
    </button>
  ) : <div {...tilt} className={cls}>{body}</div>;
}

export function RingStat({ label, pct, tone = "brand", detail }: { label: string; pct: number | null | undefined; tone?: Tone; detail?: string }) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const color = { brand: "hsl(var(--primary))", good: "hsl(var(--good))", warn: "hsl(var(--warn))", bad: "hsl(var(--bad))", neutral: "hsl(var(--muted-foreground))" }[tone];
  const tilt = useTilt(5);
  return (
    <div {...tilt} className="glass tilt-3d flex items-center gap-4 p-4">
      <div
        role="img" aria-label={`${label} ${pct == null ? "not available" : fmtPct(pct)}`}
        className="grid h-16 w-16 shrink-0 place-items-center rounded-full"
        style={{ background: `conic-gradient(${color} ${p * 3.6}deg, hsl(var(--muted)) 0)` }}
      >
        <div className="grid h-12 w-12 place-items-center rounded-full bg-card text-sm font-semibold tabular">{pct == null ? "–" : `${Math.round(p)}%`}</div>
      </div>
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        {detail && <p className="mt-0.5 text-xs tabular text-muted-foreground">{detail}</p>}
      </div>
    </div>
  );
}

/** % change badge. `goodWhenDown` flips the colour for metrics where less is better (pending). */
export function DeltaBadge({ change, goodWhenDown }: { change: Change; goodWhenDown?: boolean }) {
  if (change.direction === "flat") return <Badge><ArrowRight className="h-3 w-3" /> 0%</Badge>;
  const up = change.direction === "up";
  const good = goodWhenDown ? !up : up;
  const txt = change.pct_change == null ? `${up ? "+" : ""}${fmtInt(change.delta)}` : `${up ? "+" : ""}${change.pct_change.toFixed(1)}%`;
  return (
    <Badge tone={good ? "good" : "bad"} aria-label={`${up ? "increase" : "decrease"} of ${txt}`}>
      {up ? <ArrowUpRight className="h-3 w-3" aria-hidden /> : <ArrowDownRight className="h-3 w-3" aria-hidden />} {txt}
    </Badge>
  );
}

export function ChartCard({ title, subtitle, children, action, className }: {
  title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode; className?: string;
}) {
  return (
    <Card className={className}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}

export function QueryError({ error }: { error?: unknown }) {
  return (
    <div role="alert" className="flex items-center gap-2 rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
      <AlertCircle className="h-4 w-4" /> {error instanceof Error ? error.message : "Something went wrong loading this data."}
    </div>
  );
}

export const Loading = ({ h = 280 }: { h?: number }) => <Skeleton className="w-full" />;
export function ChartSkeleton({ h = 280 }: { h?: number }) {
  return <div style={{ height: h }}><Skeleton className="h-full w-full" /></div>;
}
