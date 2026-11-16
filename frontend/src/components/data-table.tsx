"use client";
import { useMemo } from "react";
import { ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { fmtDate, label } from "@/lib/format";
import { cn } from "@/lib/utils";

type Row = Record<string, string | number | null>;

const isDateKey = (k: string) => k.endsWith("_date");
const WIDE = new Set(["comments_to_shopper", "qc_feedback", "client_escalation", "location", "form_name", "other_columns"]);

/** Server-driven table: sorting / paging live in the parent, TanStack Table does the rendering. */
export function RecordsTable({
  columns, rows, sort, order, onSort, caption,
}: {
  columns: string[]; rows: Row[]; sort?: string; order?: "asc" | "desc";
  onSort?: (key: string) => void; caption: string;
}) {
  const defs = useMemo<ColumnDef<Row>[]>(
    () => columns.map((k) => ({
      id: k, accessorKey: k, header: label(k),
      cell: (c) => {
        const v = c.getValue() as string | number | null;
        return v == null || v === "" ? <span className="text-muted-foreground">–</span> : isDateKey(k) ? fmtDate(String(v)) : String(v);
      },
    })),
    [columns],
  );
  const table = useReactTable({ data: rows, columns: defs, getCoreRowModel: getCoreRowModel() });

  return (
    <div className="overflow-auto rounded-xl border">
      <table className="w-full min-w-max text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-muted/90 backdrop-blur">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const key = h.column.id;
                const active = sort === key;
                return (
                  <th key={h.id} scope="col" aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"} className="whitespace-nowrap px-3 py-2 font-medium">
                    {onSort ? (
                      <button onClick={() => onSort(key)} className="inline-flex items-center gap-1 hover:text-primary">
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {active ? (order === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ChevronsUpDown className="h-3 w-3 opacity-40" />}
                      </button>
                    ) : flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((r) => (
            <tr key={r.id} className="border-t hover:bg-muted/40">
              {r.getVisibleCells().map((c) => (
                <td key={c.id} className={cn("px-3 py-2 align-top tabular", WIDE.has(c.column.id) ? "max-w-[22rem] truncate" : "whitespace-nowrap")}
                  title={WIDE.has(c.column.id) ? String(c.getValue() ?? "") : undefined}>
                  {flexRender(c.column.columnDef.cell, c.getContext())}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={columns.length} className="px-3 py-10 text-center text-muted-foreground">No records match these filters.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-2 pt-3 text-sm text-muted-foreground">
      <span className="tabular">{total === 0 ? "0 records" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total.toLocaleString("en-US")}`}</span>
      <div className="flex items-center gap-1">
        <button className="rounded-lg border px-3 py-1 hover:bg-muted disabled:opacity-40" disabled={page <= 1} onClick={() => onPage(page - 1)}>Prev</button>
        <span className="px-2 tabular">{page} / {pages}</span>
        <button className="rounded-lg border px-3 py-1 hover:bg-muted disabled:opacity-40" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}
