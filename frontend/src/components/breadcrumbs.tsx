"use client";
import { ChevronRight } from "lucide-react";
import { useMeta } from "@/lib/hooks";
import { useFilterStore } from "@/lib/store";

/** Overall > Client > Project > Editor. Each crumb clears everything below it. */
export function Breadcrumbs() {
  const { data: meta } = useMeta();
  const f = useFilterStore((s) => s.filters);
  const patch = useFilterStore((s) => s.patch);

  const client = meta?.clients.find((c) => c.id === f.client_id);
  const project = meta?.projects.find((p) => p.id === f.project_id);
  const editor = meta?.editors.find((e) => e.id === f.editor_id);

  const crumbs: { label: string; onClick?: () => void }[] = [
    { label: "Overall", onClick: f.client_id || f.project_id || f.editor_id ? () => patch({ client_id: undefined, project_id: undefined, editor_id: undefined }) : undefined },
  ];
  if (client) crumbs.push({ label: client.name, onClick: f.project_id || f.editor_id ? () => patch({ project_id: undefined, editor_id: undefined }) : undefined });
  if (project) crumbs.push({ label: project.name, onClick: f.editor_id ? () => patch({ editor_id: undefined }) : undefined });
  if (editor) crumbs.push({ label: editor.name });

  return (
    <nav aria-label="Drill-down" className="flex flex-wrap items-center gap-1 text-sm">
      {crumbs.map((c, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />}
          {c.onClick ? (
            <button onClick={c.onClick} className="rounded-md px-1.5 py-0.5 text-primary hover:bg-primary/10">{c.label}</button>
          ) : (
            <span aria-current={i === crumbs.length - 1 ? "page" : undefined} className="px-1.5 py-0.5 font-medium">{c.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
