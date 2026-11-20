"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { Badge, Button, Card, Input, Select, Tabs } from "@/components/ui/primitives";
import { PageHeader, QueryError } from "@/components/widgets";
import { api, del, patch, post, put } from "@/lib/api";
import { useMe, useMeta } from "@/lib/hooks";

type Tab = "status" | "columns" | "rules" | "projects" | "users" | "settings";
const TABS: { value: Tab; label: string }[] = [
  { value: "status", label: "Status map" }, { value: "columns", label: "Column map" }, { value: "rules", label: "Sheet rules" },
  { value: "projects", label: "Projects" }, { value: "users", label: "Users" }, { value: "settings", label: "Settings" },
];

export default function AdminPage() {
  const { data: me, isLoading } = useMe();
  const [tab, setTab] = useState<Tab>("status");
  if (isLoading) return null;
  if (me?.role !== "admin") return <QueryError error={new Error("Admin role required.")} />;
  return (
    <>
      <PageHeader title="Admin" subtitle="Mapping manager, sheet include/exclude rules, refresh schedule, users and roles" />
      <div className="mb-4"><Tabs label="Admin sections" value={tab} onChange={setTab} items={TABS} /></div>
      {tab === "status" && <StatusMap />}
      {tab === "columns" && <ColumnMap />}
      {tab === "rules" && <SheetRules />}
      {tab === "projects" && <Projects />}
      {tab === "users" && <Users />}
      {tab === "settings" && <Settings />}
    </>
  );
}

function useAdmin<T>(key: string, path: string) {
  return useQuery({ queryKey: ["admin", key], queryFn: () => api<T>(path) });
}
function useInvalidate(key: string) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["admin", key] });
}

const Th = ({ children }: { children?: React.ReactNode }) => <th scope="col" className="px-3 py-2 font-medium">{children}</th>;
const Table = ({ head, children, caption }: { head: string[]; children: React.ReactNode; caption: string }) => (
  <div className="overflow-auto rounded-xl border">
    <table className="w-full min-w-[40rem] text-left text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead className="bg-muted/80"><tr>{head.map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
      <tbody>{children}</tbody>
    </table>
  </div>
);

/* ------------------------------------------------------------------ status map */
interface StatusRow { id: number; field: string; source_value_norm: string; canonical_value: string; counts_as_edited: boolean; counts_as_finalised: boolean; is_hold_or_incomplete: boolean }
function StatusMap() {
  const q = useAdmin<StatusRow[]>("status", "/admin/status-map");
  const inv = useInvalidate("status");
  const save = useMutation({
    mutationFn: (r: StatusRow & { source_value?: string }) => put("/admin/status-map", { field: r.field, source_value: r.source_value ?? r.source_value_norm, canonical_value: r.canonical_value, counts_as_edited: r.counts_as_edited, counts_as_finalised: r.counts_as_finalised, is_hold_or_incomplete: r.is_hold_or_incomplete }),
    onSuccess: inv,
  });
  const [field, setField] = useState("edit_status");
  const [src, setSrc] = useState("");
  const [canon, setCanon] = useState("");
  const [edited, setEdited] = useState(false);
  const [finalised, setFinalised] = useState(false);
  const add = useMutation({
    mutationFn: () => put("/admin/status-map", { field, source_value: src, canonical_value: canon || src, counts_as_edited: edited, counts_as_finalised: finalised, is_hold_or_incomplete: false }),
    onSuccess: () => { setSrc(""); setCanon(""); setEdited(false); setFinalised(false); inv(); },
  });
  const rows = (q.data ?? []).filter((r) => r.field === field);
  return (
    <Card>
      <p className="mb-3 text-sm text-muted-foreground">
        Defines what counts as <strong>Edited</strong>. (<strong>Finalised</strong> counts every handled form, whatever its status.) Changes apply to all history immediately (no re-sync needed).
        Only <em>Edited &amp; Saved</em> counts as Edited by default. Values listed under “Unmapped statuses” on Data Health can be added here.
      </p>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <Select label="Field" className="w-40" value={field} onChange={(v) => setField(v || "edit_status")} placeholder="Choose"
          options={["edit_status", "qc_status", "input_status"].map((f) => ({ value: f, label: f.replace("_", " ") }))} />
        <label className="flex flex-col gap-1"><span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Sheet value</span><Input className="h-9 w-48" value={src} onChange={(e) => setSrc(e.target.value)} placeholder="e.g. Pend to QA" /></label>
        <label className="flex flex-col gap-1"><span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Show as</span><Input className="h-9 w-48" value={canon} onChange={(e) => setCanon(e.target.value)} placeholder="same as sheet value" /></label>
        <label className="flex items-center gap-1.5 pb-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={edited} onChange={(e) => setEdited(e.target.checked)} /> Edited</label>
        <label className="flex items-center gap-1.5 pb-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={finalised} onChange={(e) => setFinalised(e.target.checked)} /> Finalised</label>
        <Button variant="brand" size="sm" disabled={!src || add.isPending} onClick={() => add.mutate()}>Add / update</Button>
      </div>
      {add.isError && <QueryError error={add.error} />}
      {q.isError && <QueryError error={q.error} />}
      {save.isError && <QueryError error={save.error} />}
      <Table caption="Ops status mapping" head={["Source value", "Canonical", "Counts as edited", "Counts as finalised", "Hold / incomplete"]}>
        {rows.map((r) => (
          <tr key={r.id} className="border-t">
            <td className="px-3 py-2 text-muted-foreground">{r.source_value_norm}</td>
            <td className="px-3 py-2 font-medium">{r.canonical_value}</td>
            {(["counts_as_edited", "counts_as_finalised", "is_hold_or_incomplete"] as const).map((k) => (
              <td key={k} className="px-3 py-2">
                <input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={r[k]} aria-label={`${r.canonical_value}: ${k.replace(/_/g, " ")}`}
                  onChange={(e) => save.mutate({ ...r, [k]: e.target.checked })} />
              </td>
            ))}
          </tr>
        ))}
      </Table>
    </Card>
  );
}

/* ------------------------------------------------------------------ column map */
interface ColRow { id: number; scope: string; scope_ref: string; sheet_kind: string; source_header_norm: string; canonical_field: string }
function ColumnMap() {
  const q = useAdmin<ColRow[]>("columns", "/admin/column-map");
  const inv = useInvalidate("columns");
  const [kind, setKind] = useState("operational");
  const [header, setHeader] = useState("");
  const [field, setField] = useState("");
  const add = useMutation({
    mutationFn: () => post("/admin/column-map", { sheet_kind: kind, source_header: header, canonical_field: field }),
    onSuccess: () => { setHeader(""); inv(); },
  });
  const rm = useMutation({ mutationFn: (id: number) => del(`/admin/column-map/${id}`), onSuccess: inv });
  const fields = Array.from(new Set((q.data ?? []).map((r) => r.canonical_field))).sort();
  const rows = (q.data ?? []).filter((r) => r.sheet_kind === kind);
  return (
    <Card>
      <p className="mb-3 text-sm text-muted-foreground">Maps differing sheet headers to canonical fields. Re-run a full sync to apply new mappings to existing files.</p>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <Select label="Sheet kind" className="w-40" value={kind} onChange={(v) => setKind(v || "operational")} placeholder="Choose" options={["operational", "rework", "escalation"].map((k) => ({ value: k, label: k }))} />
        <label className="flex flex-col gap-1"><span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Header text</span><Input className="h-9 w-56" value={header} onChange={(e) => setHeader(e.target.value)} placeholder="e.g. Date Received" /></label>
        <Select label="Canonical field" className="w-52" value={field} onChange={setField} placeholder="Choose" options={fields.map((f) => ({ value: f, label: f }))} />
        <Button variant="brand" size="sm" disabled={!header || !field || add.isPending} onClick={() => add.mutate()}>Add mapping</Button>
      </div>
      {add.isError && <QueryError error={add.error} />}
      <Table caption="Column mappings" head={["Header (normalised)", "Canonical field", "Scope", ""]}>
        {rows.map((r) => (
          <tr key={r.id} className="border-t">
            <td className="px-3 py-2 font-mono text-xs">{r.source_header_norm}</td>
            <td className="px-3 py-2">{r.canonical_field}</td>
            <td className="px-3 py-2 text-muted-foreground">{r.scope}{r.scope_ref ? `: ${r.scope_ref}` : ""}</td>
            <td className="px-3 py-2"><Button size="icon" variant="ghost" aria-label={`Delete mapping ${r.source_header_norm}`} onClick={() => rm.mutate(r.id)}><Trash2 className="h-4 w-4" /></Button></td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

/* ------------------------------------------------------------------ sheet rules */
interface RuleRow { id: number; priority: number; pattern: string; kind: string; include: boolean; read_cells: boolean }
function SheetRules() {
  const q = useAdmin<RuleRow[]>("rules", "/admin/sheet-rules");
  const inv = useInvalidate("rules");
  const [pattern, setPattern] = useState("");
  const [kind, setKind] = useState("ignored");
  const [priority, setPriority] = useState("100");
  const add = useMutation({
    mutationFn: () => post("/admin/sheet-rules", { priority: Number(priority), pattern, kind, include: kind !== "ignored", read_cells: kind !== "ignored" }),
    onSuccess: () => { setPattern(""); inv(); },
  });
  const rm = useMutation({ mutationFn: (id: number) => del(`/admin/sheet-rules/${id}`), onSuccess: inv });
  return (
    <Card>
      <p className="mb-3 text-sm text-muted-foreground">First matching rule (lowest priority number) classifies a tab. Tabs set to <em>never read</em> are not fetched at all (used for credential tabs).</p>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1"><span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Tab name regex</span><Input className="h-9 w-56" value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="^archive" /></label>
        <Select label="Kind" className="w-40" value={kind} onChange={(v) => setKind(v || "ignored")} placeholder="Choose" options={["operational", "rework", "escalation", "master", "ignored"].map((k) => ({ value: k, label: k }))} />
        <label className="flex flex-col gap-1"><span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Priority</span><Input className="h-9 w-24" type="number" value={priority} onChange={(e) => setPriority(e.target.value)} /></label>
        <Button variant="brand" size="sm" disabled={!pattern || add.isPending} onClick={() => add.mutate()}>Add rule</Button>
      </div>
      {add.isError && <QueryError error={add.error} />}
      <Table caption="Sheet rules" head={["Priority", "Pattern", "Kind", "Counts in totals", "Cells read", ""]}>
        {(q.data ?? []).map((r) => (
          <tr key={r.id} className="border-t">
            <td className="px-3 py-2 tabular">{r.priority}</td>
            <td className="px-3 py-2 font-mono text-xs">{r.pattern}</td>
            <td className="px-3 py-2">{r.kind}</td>
            <td className="px-3 py-2"><Badge tone={r.include ? "good" : "neutral"}>{r.include ? "yes" : "no"}</Badge></td>
            <td className="px-3 py-2"><Badge tone={r.read_cells ? "brand" : "bad"}>{r.read_cells ? "read" : "never read"}</Badge></td>
            <td className="px-3 py-2"><Button size="icon" variant="ghost" aria-label={`Delete rule ${r.pattern}`} onClick={() => rm.mutate(r.id)}><Trash2 className="h-4 w-4" /></Button></td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

/* ------------------------------------------------------------------ projects */
function Projects() {
  const { data: meta } = useMeta();
  const qc = useQueryClient();
  const set = useMutation({
    mutationFn: ({ id, v }: { id: number; v: boolean | null }) => patch(`/admin/projects/${id}`, { qc_applicable_override: v }),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <Card>
      <p className="mb-3 text-sm text-muted-foreground">A project is “QC applicable” once any row has a QC member or date. Override it here; “Auto” follows the data.</p>
      <Table caption="Project QC applicability" head={["Project", "QC applicable now", "Override"]}>
        {(meta?.projects ?? []).map((p) => (
          <tr key={p.id} className="border-t">
            <th scope="row" className="px-3 py-2 text-left font-medium">{p.name}</th>
            <td className="px-3 py-2"><Badge tone={p.qc_applicable ? "good" : "neutral"}>{p.qc_applicable ? "yes" : "no"}</Badge></td>
            <td className="px-3 py-2">
              <select aria-label={`QC override for ${p.name}`} className="h-8 rounded-lg border bg-card/60 px-2" defaultValue="auto"
                onChange={(e) => set.mutate({ id: p.id, v: e.target.value === "auto" ? null : e.target.value === "yes" })}>
                <option value="auto">Auto</option><option value="yes">Always</option><option value="no">Never</option>
              </select>
            </td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

/* ------------------------------------------------------------------ users */
interface UserRow { id: number; email: string; name: string; role: string; active: boolean; last_login_at: string | null }
function Users() {
  const q = useAdmin<UserRow[]>("users", "/admin/users");
  const inv = useInvalidate("users");
  const { data: me } = useMe();
  const [f, setF] = useState({ email: "", name: "", role: "viewer", password: "" });
  const add = useMutation({ mutationFn: () => post("/admin/users", f), onSuccess: () => { setF({ email: "", name: "", role: "viewer", password: "" }); inv(); } });
  const upd = useMutation({ mutationFn: ({ id, ...b }: { id: number; role?: string; active?: boolean }) => patch(`/admin/users/${id}`, b), onSuccess: inv });
  return (
    <Card>
      <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <Input type="email" placeholder="Email" aria-label="Email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        <Input placeholder="Name" aria-label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <select aria-label="Role" className="h-10 rounded-xl border bg-card/60 px-3 text-sm" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
          <option value="viewer">Viewer</option><option value="manager">Manager</option><option value="admin">Admin</option>
        </select>
        <Input type="password" placeholder="Password (10+ chars)" aria-label="Password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <Button variant="brand" disabled={!f.email || !f.name || f.password.length < 10 || add.isPending} onClick={() => add.mutate()}>Add user</Button>
      </div>
      {add.isError && <QueryError error={add.error} />}
      {upd.isError && <QueryError error={upd.error} />}
      <Table caption="Users" head={["User", "Role", "Active", "Last sign-in"]}>
        {(q.data ?? []).map((u) => (
          <tr key={u.id} className="border-t">
            <td className="px-3 py-2">{u.name}<span className="block text-xs text-muted-foreground">{u.email}</span></td>
            <td className="px-3 py-2">
              <select aria-label={`Role for ${u.email}`} className="h-8 rounded-lg border bg-card/60 px-2" value={u.role} disabled={u.id === me?.id}
                onChange={(e) => upd.mutate({ id: u.id, role: e.target.value })}>
                <option value="viewer">Viewer</option><option value="manager">Manager</option><option value="admin">Admin</option>
              </select>
            </td>
            <td className="px-3 py-2"><input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={u.active} disabled={u.id === me?.id} aria-label={`Active: ${u.email}`} onChange={(e) => upd.mutate({ id: u.id, active: e.target.checked })} /></td>
            <td className="px-3 py-2 text-muted-foreground">{u.last_login_at ? new Date(u.last_login_at).toLocaleString("en-GB") : "never"}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

/* ------------------------------------------------------------------ settings */
function Settings() {
  const q = useAdmin<{ refresh_schedule?: { interval_minutes: number }; level_labels?: Record<string, string> }>("settings", "/admin/settings");
  const inv = useInvalidate("settings");
  const [mins, setMins] = useState<string>("");
  const [labels, setLabels] = useState<Record<string, string> | null>(null);
  const shownMins = mins || String(q.data?.refresh_schedule?.interval_minutes ?? 120);
  const shownLabels = labels ?? q.data?.level_labels ?? { level1: "Client", level2: "Project", level3: "Form" };
  const saveSched = useMutation({ mutationFn: () => put("/admin/settings/refresh_schedule", { interval_minutes: Number(shownMins) }), onSuccess: inv });
  const saveLabels = useMutation({ mutationFn: () => put("/admin/settings/level_labels", shownLabels), onSuccess: inv });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <h2 className="mb-1 text-sm font-semibold">Refresh schedule</h2>
        <p className="mb-3 text-xs text-muted-foreground">How often the scheduled sync runs (5 to 1440 minutes). Needs SCHEDULER_ENABLED on the server.</p>
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-1 text-sm">Every (minutes)<Input type="number" className="h-9 w-32" value={shownMins} onChange={(e) => setMins(e.target.value)} /></label>
          <Button variant="brand" size="sm" onClick={() => saveSched.mutate()} disabled={saveSched.isPending}>Save</Button>
        </div>
        {saveSched.isError && <div className="mt-3"><QueryError error={saveSched.error} /></div>}
        {saveSched.isSuccess && <p className="mt-2 text-sm text-good">Saved.</p>}
      </Card>
      <Card>
        <h2 className="mb-1 text-sm font-semibold">Hierarchy labels</h2>
        <p className="mb-3 text-xs text-muted-foreground">Words the business uses for the three levels (file prefix, middle of the file name, Form column).</p>
        <div className="grid gap-2 sm:grid-cols-3">
          {(["level1", "level2", "level3"] as const).map((k, i) => (
            <label key={k} className="flex flex-col gap-1 text-sm">Level {i + 1}
              <Input className="h-9" value={shownLabels[k] ?? ""} onChange={(e) => setLabels({ ...shownLabels, [k]: e.target.value })} />
            </label>
          ))}
        </div>
        <Button className="mt-3" variant="brand" size="sm" onClick={() => saveLabels.mutate()} disabled={saveLabels.isPending}>Save labels</Button>
        {saveLabels.isSuccess && <p className="mt-2 text-sm text-good">Saved. The UI will adopt these labels in a later phase.</p>}
      </Card>
    </div>
  );
}
