"use client";
import { useEffect, useMemo, useState } from "react";
import { Filter, RotateCcw, X } from "lucide-react";
import { Button, Input, Select } from "./ui/primitives";
import { useMeta } from "@/lib/hooks";
import { useFilterStore } from "@/lib/store";
import { MONTHS } from "@/lib/format";
import { monthsOfQuarter, weeksInPeriod, type Filters } from "@/lib/filters";

const ALL = "all";
const num = (v: string) => (v === "" ? undefined : Number(v));
const Label = ({ children }: { children: React.ReactNode }) => (
  <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{children}</span>
);

/**
 * Period filters are nested and always consistent: Year > Quarter (Q1 Jan-Mar, Q2 Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec)
 * > Month (only the months of the chosen quarter) > Week (only the weeks inside the chosen month / quarter).
 * Everything else (client, project, editor, statuses) narrows the data inside that period, on every page.
 */
export function FilterBar() {
  const { data: meta, isPlaceholderData } = useMeta();
  const f = useFilterStore((s) => s.filters);
  const patch = useFilterStore((s) => s.patch);
  const reset = useFilterStore((s) => s.reset);
  const [open, setOpen] = useState(false);

  const years = useMemo(() => {
    const a = meta?.data_range.from ? Number(meta.data_range.from.slice(0, 4)) : new Date().getFullYear() - 2;
    const b = Math.max(meta?.data_range.to ? Number(meta.data_range.to.slice(0, 4)) : 0, new Date().getFullYear());
    return Array.from({ length: b - a + 1 }, (_, i) => b - i).map((y) => ({ value: y, label: String(y) }));
  }, [meta]);
  const latestYear = years[0]?.value;

  const monthOptions = (f.quarter ? monthsOfQuarter(f.quarter) : MONTHS.map((_, i) => i + 1))
    .map((m) => ({ value: m, label: MONTHS[m - 1] }));
  const weekOptions = useMemo(
    () => (f.year ? weeksInPeriod(f.year, f.quarter, f.month).map((w) => ({ value: w.week, label: w.label })) : []),
    [f.year, f.quarter, f.month],
  );

  // a client / project / editor that is not in the newly chosen period's sheets cannot stay selected
  useEffect(() => {
    if (!meta || isPlaceholderData) return;
    const drop: Partial<Filters> = {};
    if (f.client_id && !meta.clients.some((c) => c.id === f.client_id)) drop.client_id = undefined;
    if (f.project_id && !meta.projects.some((p) => p.id === f.project_id)) drop.project_id = undefined;
    if (f.editor_id && !meta.editors.some((e) => e.id === f.editor_id) && !meta.qc_members.some((e) => e.id === f.editor_id)) drop.editor_id = undefined;
    if (Object.keys(drop).length) patch(drop);
  }, [meta, isPlaceholderData, f.client_id, f.project_id, f.editor_id, patch]);

  const projects = (meta?.projects ?? []).filter((p) => !f.client_id || p.client_id === f.client_id);
  const active = Object.keys(f).length;
  // quarter / month / week only narrow a single year, so they wait while a date range or "All years" is active
  const custom = !!(f.date_from || f.date_to || f.range === "all");

  const set = (p: Partial<Filters>) => patch(p);
  // any period level needs a year to mean anything: default to the latest one
  const withYear = (p: Partial<Filters>): Partial<Filters> => ({ ...p, ...(f.year ? {} : { year: latestYear }) });
  const setClient = (v: string) => {
    const id = num(v);
    const proj = projects.find((p) => p.id === f.project_id);
    set({ client_id: id, project_id: proj && id && proj.client_id !== id ? undefined : f.project_id });
  };

  return (
    <div className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur-xl">
      <div className="flex items-center gap-2 px-3 py-2 sm:px-6 lg:hidden">
        <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="filters-panel">
          <Filter className="h-4 w-4" /> Filters{active ? ` (${active})` : ""}
        </Button>
        {active > 0 && <Button variant="ghost" size="sm" onClick={reset}><X className="h-4 w-4" /> Clear</Button>}
      </div>

      <div id="filters-panel" className={`${open ? "block" : "hidden"} space-y-3 px-3 pb-3 sm:px-6 lg:block lg:py-3`}>
        <fieldset className="grid grid-cols-2 items-end gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <legend className="sr-only">Period</legend>
          <Select label="Year" value={f.range === "all" ? ALL : f.year} placeholder={`${new Date().getFullYear()} (whole year)`}
            onChange={(v) => (v === ALL ? set({ range: "all" }) : set({ year: num(v) }))}
            options={[{ value: ALL, label: "All years" }, ...years]} />
          <Select label="Quarter" value={f.quarter} disabled={custom} onChange={(v) => set(withYear({ quarter: num(v) }))}
            options={[1, 2, 3, 4].map((q) => ({ value: q, label: `Q${q} · ${MONTHS[3 * q - 3]}–${MONTHS[3 * q - 1]}` }))} placeholder="Whole year" />
          <Select label="Month" value={f.month} disabled={custom} onChange={(v) => set(withYear({ month: num(v) }))}
            options={monthOptions} placeholder={f.quarter ? `Whole Q${f.quarter}` : "Whole period"} />
          <Select label="Week" value={f.week} disabled={custom || !f.year} onChange={(v) => set({ week: num(v) })}
            options={weekOptions} placeholder={f.year ? "Whole period" : "Pick a year"} />
          <label className="flex flex-col gap-1">
            <Label>From</Label>
            <Input type="date" className="h-9" value={f.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value || undefined })} />
          </label>
          <label className="flex flex-col gap-1">
            <Label>To</Label>
            <Input type="date" className="h-9" value={f.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value || undefined })} />
          </label>
        </fieldset>

        <fieldset className="grid grid-cols-2 items-end gap-2 sm:grid-cols-3 lg:grid-cols-5">
          <legend className="sr-only">Scope</legend>
          <Select label="Client" value={f.client_id} onChange={setClient}
            options={(meta?.clients ?? []).map((c) => ({ value: c.id, label: c.name }))} />
          <Select label="Project" value={f.project_id} onChange={(v) => set({ project_id: num(v) })}
            options={projects.map((p) => ({ value: p.id, label: p.name }))} />
          <Select label="Editor" value={f.editor_id} onChange={(v) => set({ editor_id: num(v) })}
            options={(meta?.editors ?? []).map((e) => ({ value: e.id, label: e.name }))} />
          <Select label="QC status" value={f.qc_status} onChange={(v) => set({ qc_status: v || undefined })}
            options={(meta?.qc_statuses ?? []).map((s) => ({ value: s, label: s }))} />
          <div className="flex items-end">
            <Button variant="ghost" size="sm" onClick={reset} disabled={!active} title="Reset filters (whole current year)">
              <RotateCcw className="h-4 w-4" /> Reset
            </Button>
          </div>
        </fieldset>
      </div>
    </div>
  );
}
