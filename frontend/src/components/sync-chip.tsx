"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { SyncStatus } from "@/lib/types";

function ago(iso?: string | null, now = Date.now()) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/**
 * Keeps the whole dashboard live: polls the sync state, and whenever a sync finishes with new data from
 * Drive (or every 20 seconds while one is running) every number on every page is refetched.
 */
export function SyncChip() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sync-status"], queryFn: () => api<SyncStatus>("/sync/status"), refetchInterval: 10_000 });
  const [now, setNow] = useState(() => Date.now());
  const [toast, setToast] = useState(false);
  const seen = useRef<string | null>(null);
  const d = q.data;

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 10_000); return () => clearInterval(t); }, []);

  const marker = d ? `${d.last_change?.id ?? 0}:${d.last_change?.finished_at ?? ""}` : null;
  useEffect(() => {
    if (!marker) return;
    if (seen.current && seen.current !== marker) {
      qc.invalidateQueries({ predicate: (qq) => qq.queryKey[0] !== "sync-status" });
      setToast(true);
      const t = setTimeout(() => setToast(false), 7000);
      seen.current = marker;
      return () => clearTimeout(t);
    }
    seen.current = marker;
  }, [marker, qc]);

  useEffect(() => {
    if (!d?.running) return;
    const t = setInterval(() => qc.invalidateQueries({ predicate: (qq) => qq.queryKey[0] !== "sync-status" }), 20_000);
    return () => clearInterval(t);
  }, [d?.running, qc]);

  if (!d) return null;
  const pct = d.last?.progress_pct;
  return (
    <>
      <Link href="/health" className="hidden items-center gap-1.5 rounded-xl border bg-card/60 px-2.5 py-1.5 text-xs hover:bg-muted sm:flex"
        title={`Drive is checked ${d.auto_sync.enabled ? `automatically every ${d.auto_sync.interval_minutes ?? "?"} minutes` : "manually (auto-sync is off)"}. Last data change ${ago(d.last_change?.finished_at, now)}.`}>
        {d.running ? (
          <><RefreshCw className="h-3.5 w-3.5 animate-spin text-primary" aria-hidden /> Syncing{pct != null ? ` ${Math.round(pct)}%` : "…"}</>
        ) : (
          <><CheckCircle2 className={`h-3.5 w-3.5 ${d.auto_sync.enabled ? "text-good" : "text-warn"}`} aria-hidden />
            {d.auto_sync.enabled ? "Live" : "Manual"} · checked {ago(d.heartbeat?.checked_at ?? d.last?.finished_at, now)}</>
        )}
      </Link>
      {toast && (
        <div role="status" className="glass fixed bottom-4 right-4 z-50 flex items-center gap-2 px-4 py-3 text-sm animate-fade-up">
          <CheckCircle2 className="h-4 w-4 text-good" /> New data from Drive loaded. Pages are refreshed.
        </div>
      )}
    </>
  );
}
