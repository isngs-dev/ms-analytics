"use client";
import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Skeleton, Tabs } from "./ui/primitives";
import { Boundary } from "./three/boundary";
import { RankBars } from "./charts";
import { ChartCard, QueryError } from "./widgets";
import { api } from "@/lib/api";
import { useApiFilters, useMeta } from "@/lib/hooks";
import { useFilterStore } from "@/lib/store";
import { useUse3D, useWide } from "@/lib/visual";
import { fmtInt } from "@/lib/format";
import type { BreakdownResp } from "@/lib/types";
import type { CityEditor, CityRow } from "./three/city-scene";

const CityScene = dynamic(() => import("./three/city-scene"), { ssr: false, loading: () => <Skeleton className="h-[460px] w-full" /> });

type View = "city" | "bars";

/**
 * Client / project volumes as a 3D bar city (height = forms received) with a flat 2D bar alternative.
 * The city always shows every client so the camera can fly Overall -> Client -> Project -> Editor
 * as the drill-down filters change; the table / detail below follow the same filters.
 */
export function BarCity() {
  const { use3D, reason } = useUse3D();
  const roomy = useWide(640);
  const [view, setView] = useState<View>("city");
  // a phone-width city is too small to read: start flat there (the tabs still allow 3D)
  useEffect(() => { if (!roomy) setView("bars"); }, [roomy]);
  const f = useApiFilters();
  const patch = useFilterStore((s) => s.patch);
  const { data: meta } = useMeta();

  // everything except the drill-down dimensions, so the city does not collapse as you drill
  const { client_id, project_id, editor_id, ...base } = f as Record<string, string | number>;
  const proj = useQuery({
    queryKey: ["city", base],
    queryFn: () => api<BreakdownResp>("/analytics/breakdown", { ...base, by: "project" }),
    placeholderData: keepPreviousData,
  });
  const eds = useQuery({
    queryKey: ["city-editors", base, project_id],
    queryFn: () => api<BreakdownResp>("/analytics/breakdown", { ...base, by: "editor", project_id }),
    enabled: project_id != null,
    placeholderData: keepPreviousData,
  });

  const rows = useMemo<CityRow[]>(() => (proj.data?.rows ?? []).filter((r) => r.id != null && r.received > 0).map((r) => ({
    id: r.id as number, name: r.name, client: r.parent ?? "?", received: r.received, edited: r.edited, pending: r.pending_editing,
  })), [proj.data]);
  const editors = useMemo<CityEditor[]>(() => project_id == null ? [] : (eds.data?.rows ?? []).filter((r) => r.id != null && r.processed > 0)
    .slice(0, 10).map((r) => ({ id: r.id as number, name: r.name, value: r.processed })), [eds.data, project_id]);

  const clientName = meta?.clients.find((c) => c.id === client_id)?.name;
  const focus = { client: clientName, project: project_id as number | undefined, editor: editor_id as number | undefined };

  const pickClient = (name: string) => {
    const c = meta?.clients.find((x) => x.name === name);
    if (c) patch({ client_id: c.id, project_id: undefined, editor_id: undefined });
  };
  const pickProject = (r: CityRow) => {
    // one drill level per click: first the client, then the project
    if (clientName !== r.client) pickClient(r.client);
    else patch({ project_id: r.id, editor_id: undefined });
  };
  const pickEditor = (id: number) => patch({ editor_id: id });

  const show3D = use3D && view === "city";
  const flat = (
    <RankBars
      rows={rows.map((r) => ({ id: r.id, name: `${r.client} · ${r.name}`, values: { received: r.received, pending_editing: r.pending } }))}
      keys={["received", "pending_editing"]} limit={15} onClick={(b) => { const r = rows.find((x) => x.id === b.id); if (r) pickProject(r); }}
    />
  );

  return (
    <ChartCard
      title="Volume by client and project"
      subtitle={show3D ? "Bar height = forms received. Drag to orbit, click a bar to drill in, use the breadcrumb to go back" : "Forms received and pending editing. Click a bar to drill in"}
      action={
        <Tabs label="Chart style" value={view} onChange={setView}
          items={[{ value: "city", label: "3D city" }, { value: "bars", label: "2D bars" }]} />
      }
    >
      {proj.isError ? <QueryError error={proj.error} /> : proj.isLoading ? <Skeleton className="h-[460px] w-full" /> : show3D ? (
        <Boundary fallback={flat}>
          <CityScene rows={rows} editors={editors} focus={focus} onPickClient={pickClient} onPickProject={pickProject} onPickEditor={pickEditor} />
        </Boundary>
      ) : (
        <>
          {view === "city" && !use3D && <p className="mb-2 text-xs text-muted-foreground">Showing 2D bars{reason ? ` (${reason})` : ""}. Use the 3D toggle in the top bar to override.</p>}
          {flat}
        </>
      )}
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-muted-foreground">View as table</summary>
        <table className="mt-2 w-full text-left">
          <caption className="sr-only">Forms received by client and project</caption>
          <thead><tr className="text-xs text-muted-foreground"><th scope="col" className="py-1 font-medium">Client / project</th><th scope="col" className="py-1 text-right font-medium">Received</th><th scope="col" className="py-1 text-right font-medium">Pending</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t"><th scope="row" className="py-1 font-normal">{r.client} · {r.name}</th><td className="py-1 text-right tabular-nums">{fmtInt(r.received)}</td><td className="py-1 text-right tabular-nums">{fmtInt(r.pending)}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </ChartCard>
  );
}
