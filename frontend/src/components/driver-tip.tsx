"use client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useChangeDrivers, type DriverQuery } from "@/lib/hooks";
import { fmtDate, fmtInt } from "@/lib/format";
import type { DriverRow } from "@/lib/types";

const signed = (n: number) => (n > 0 ? `+${fmtInt(n)}` : n < 0 ? `−${fmtInt(-n)}` : "0");

/** Rows from a table that already holds every form: biggest falls and rises first, with the totals of each side. */
export function tipFromRows(all: DriverRow[], delta: number, extra: Partial<TipData> = {}, limit = 8): TipData {
  const down = all.filter((r) => r.delta < 0).sort((a, b) => a.delta - b.delta);
  const up = all.filter((r) => r.delta > 0).sort((a, b) => b.delta - a.delta);
  return {
    delta, ...extra,
    decliners: down.slice(0, limit), decliner_count: down.length, decline_total: down.reduce((a, r) => a + r.delta, 0),
    gainers: up.slice(0, limit), gainer_count: up.length, gain_total: up.reduce((a, r) => a + r.delta, 0),
  };
}

export interface TipData {
  delta: number; previousTotal?: number; currentTotal?: number; periods?: string;
  decliners: DriverRow[]; decliner_count: number; decline_total: number;
  gainers: DriverRow[]; gainer_count: number; gain_total: number;
}

function Rows({ rows, count, total, tone, title }: { rows: DriverRow[]; count: number; total: number; tone: "bad" | "good"; title: string }) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-2">
      <p className={`text-[11px] font-semibold uppercase tracking-wider ${tone === "bad" ? "text-bad" : "text-good"}`}>
        {title} <span className="font-normal normal-case text-muted-foreground">({signed(total)} in all)</span>
      </p>
      <ul className="mt-1 space-y-1">
        {rows.map((r) => (
          <li key={`${r.project_id}|${r.form}`} className="flex items-start justify-between gap-3 text-xs">
            <span className="min-w-0">
              <span className="block truncate font-medium" title={r.form}>{r.form}</span>
              {r.project && r.project !== r.form && <span className="block truncate text-muted-foreground" title={r.project}>{r.project}</span>}
            </span>
            <span className="shrink-0 text-right tabular">
              <span className="text-muted-foreground">{fmtInt(r.previous)} → {fmtInt(r.current)}</span>{" "}
              <b className={tone === "bad" ? "text-bad" : "text-good"}>{signed(r.delta)}</b>
            </span>
          </li>
        ))}
      </ul>
      {count > rows.length && <p className="mt-1 text-xs text-muted-foreground">+ {count - rows.length} more form{count - rows.length === 1 ? "" : "s"}</p>}
    </div>
  );
}

function Body({ data }: { data: TipData }) {
  const downFirst = data.delta <= 0;
  const down = <Rows key="d" rows={data.decliners} count={data.decliner_count} total={data.decline_total} tone="bad" title="Fell because of" />;
  const up = <Rows key="u" rows={data.gainers} count={data.gainer_count} total={data.gain_total} tone="good" title="Grew because of" />;
  return (
    <>
      <p className="text-sm font-semibold">
        {data.previousTotal != null && data.currentTotal != null ? <>{fmtInt(data.previousTotal)} → {fmtInt(data.currentTotal)} </> : null}
        <span className={data.delta < 0 ? "text-bad" : data.delta > 0 ? "text-good" : "text-muted-foreground"}>({signed(data.delta)})</span>
      </p>
      {data.periods && <p className="text-[11px] text-muted-foreground">{data.periods}</p>}
      {data.decliners.length === 0 && data.gainers.length === 0
        ? <p className="mt-2 text-xs text-muted-foreground">No single form changed.</p>
        : downFirst ? [down, up] : [up, down]}
    </>
  );
}

const range = (r: { from: string; to: string }) => (r.from === r.to ? fmtDate(r.from) : `${fmtDate(r.from)} – ${fmtDate(r.to)}`);

function Remote({ query }: { query: DriverQuery }) {
  const q = useChangeDrivers(query, true);
  if (q.isError) return <p className="text-xs text-bad">Could not load the forms behind this change.</p>;
  if (!q.data) return <p className="text-xs text-muted-foreground">Finding the forms behind this change…</p>;
  const d = q.data;
  return <Body data={{
    delta: d.delta, previousTotal: d.previous.total, currentTotal: d.current.total,
    periods: `${range(d.previous)}  →  ${range(d.current)}`,
    decliners: d.decliners, decliner_count: d.decliner_count, decline_total: d.decline_total,
    gainers: d.gainers, gainer_count: d.gainer_count, gain_total: d.gain_total,
  }} />;
}

const W = 360;

/**
 * Hover (or keyboard focus) popover that says WHICH forms made a number go up or down.
 * Give it `query` to fetch the forms for two periods (follows the global filters), or `data` when they are already known.
 */
export function DriverTip({ query, data, label, children }: { query?: DriverQuery; data?: TipData; label?: string; children: React.ReactNode }) {
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<{ left: number; top?: number; bottom?: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const open = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const r = ref.current?.getBoundingClientRect();
      if (!r) return;
      const left = Math.max(8, Math.min(r.left, window.innerWidth - W - 8));
      setPos(r.bottom + 280 > window.innerHeight && r.top > 280 ? { left, bottom: window.innerHeight - r.top + 6 } : { left, top: r.bottom + 6 });
    }, 180);
  }, []);
  const close = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setPos(null), 80);
  }, []);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => {
    if (!pos) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPos(null); };
    const onScroll = () => setPos(null);
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("scroll", onScroll, true); };
  }, [pos]);

  return (
    <>
      <span ref={ref} tabIndex={0} aria-describedby={pos ? id : undefined} aria-label={label}
        className="cursor-help rounded outline-offset-2" onMouseEnter={open} onMouseLeave={close} onFocus={open} onBlur={close}>
        {children}
      </span>
      {pos && typeof document !== "undefined" && createPortal(
        <div id={id} role="tooltip" style={{ position: "fixed", left: pos.left, top: pos.top, bottom: pos.bottom, width: W, zIndex: 80 }}
          onMouseEnter={() => { if (timer.current) clearTimeout(timer.current); }} onMouseLeave={close}
          className="max-h-[22rem] overflow-auto rounded-xl border bg-card p-3 text-left shadow-2xl">
          {query ? <Remote query={query} /> : data ? <Body data={data} /> : null}
        </div>, document.body)}
    </>
  );
}
