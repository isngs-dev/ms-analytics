"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { Modal } from "./ui/dialog";
import { Input } from "./ui/primitives";
import { Pager, RecordsTable } from "./data-table";
import { api } from "@/lib/api";
import { useDrill } from "@/lib/drill";
import { useApiFilters } from "@/lib/hooks";
import { serializeFilters } from "@/lib/filters";
import { useFilterStore } from "@/lib/store";
import type { RecordsResp } from "@/lib/types";

/** The rows behind any number: opens on a KPI / chart click, using the same filters + metric. */
export function DrillHost() {
  const { open, metric, title, extra, close } = useDrill();
  const f = useApiFilters();
  const filters = useFilterStore((s) => s.filters);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<string | undefined>();
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  useEffect(() => { setPage(1); setSearch(""); setSort(undefined); }, [open, metric, JSON.stringify(extra)]);

  const q = useQuery({
    queryKey: ["drill", f, metric, extra, page, search, sort, order],
    queryFn: () => api<RecordsResp>("/records/forms", { ...f, ...extra, metric, search, sort, order, page, page_size: 15 }),
    enabled: open,
    placeholderData: keepPreviousData,
  });

  const toggle = (k: string) => {
    if (sort === k) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else { setSort(k); setOrder("asc"); }
  };
  const qs = new URLSearchParams(serializeFilters({ ...filters, ...(extra as object) }));
  if (metric) qs.set("metric", metric);

  return (
    <Modal open={open} onOpenChange={(o) => !o && close()} title={title}
      description={q.data ? `${q.data.total.toLocaleString("en-US")} records · ${q.data.period.from} to ${q.data.period.to}` : "Loading records…"} wide>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input placeholder="Search job id, location, editor…" aria-label="Search records" className="max-w-xs"
          value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        <Link href={`/explorer?${qs.toString()}`} onClick={close} className="ml-auto inline-flex items-center gap-1 text-sm text-primary hover:underline">
          Open in Data Explorer <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>
      {q.isError ? <p className="py-10 text-center text-bad">Could not load records.</p> : (
        <>
          <RecordsTable caption={title} columns={q.data?.columns ?? []} rows={q.data?.rows ?? []} sort={sort} order={order} onSort={toggle} />
          <Pager page={page} pageSize={15} total={q.data?.total ?? 0} onPage={setPage} />
        </>
      )}
    </Modal>
  );
}
