export interface Metrics {
  received: number; edited: number; finalised: number; processed: number; qc_completed: number;
  pending_editing: number; qc_pending: number;
  editing_pct: number | null; qc_pct: number | null; completion_pct: number | null; edited_rate_pct: number | null;
}
export type MetricKey = "received" | "edited" | "finalised" | "processed" | "qc_completed" | "pending_editing" | "qc_pending";

export interface Period { from: string; to: string }
export interface OverviewResp { period: Period; metrics: Metrics; definitions: Record<string, string> }

export interface BreakRow extends Metrics { id: number | null; name: string; parent: string | null }
export interface BreakdownResp { period: Period; by: string; rows: BreakRow[] }

export interface SeriesPoint { bucket: string; received: number; edited: number; finalised: number; qc_completed: number }
export interface TimeseriesResp { period: Period; granularity: string; points: SeriesPoint[] }

export interface QualityRow {
  edited: number; marked_edited: number; escalated: number; came_back: number; clean: number;
  quality_pct: number | null; escalation_free_pct: number | null;
}
export interface QualityResp {
  period: Period; definition: string; by: string; overall: QualityRow;
  rows: (QualityRow & { id: number; name: string; parent: string | null })[];
}

export interface Change { current: number; previous: number; delta: number; pct_change: number | null; direction: "up" | "down" | "flat" }
export interface CompareProject {
  project_id: number; project: string; client: string; flags: string[];
  received: Change; edited: Change; qc_completed: Change; pending_editing: Change; qc_pending: Change;
}
export interface Alert {
  type: string; severity: "high" | "medium"; project_id: number; project: string; client: string; detail: string;
  series?: { month: string; rate_pct: number | null }[];
}
export interface CompareResp {
  mode: string; partial: boolean; current: Period; previous: Period; overall: Record<string, Change>;
  projects: CompareProject[]; alerts: Alert[];
}

export interface MetaResp {
  clients: { id: number; name: string }[];
  projects: { id: number; name: string; client_id: number; qc_applicable: boolean }[];
  editors: { id: number; name: string }[];
  qc_members: { id: number; name: string }[];
  edit_statuses: string[]; qc_statuses: string[]; editor_types: string[];
  data_range: { from: string | null; to: string | null };
  last_sync: { id: number; finished_at: string | null; status: string } | null;
}

export interface Me { id: number; email: string; name: string; role: "viewer" | "manager" | "admin" }

export interface RecordsResp {
  total: number; page: number; page_size: number; columns: string[]; rows: Record<string, string | number | null>[];
  period: Period;
}

export interface EditorsResp { period: Period; totals: Metrics; editors: BreakRow[]; by_type: BreakRow[] }
export interface EditorDetail {
  editor: { id: number; name: string }; metrics: Metrics; by_client: BreakRow[]; by_project: BreakRow[]; output: SeriesPoint[];
}
export interface QcResp {
  period: Period; members: BreakRow[];
  backlog_by_project: { project_id: number; project: string; client: string; qc_pending: number; qc_completed: number }[];
  totals: { qc_completed: number; qc_pending: number; qc_pct: number | null };
}
export interface Group { id: number | null; name: string; count: number }
export interface EscSummary {
  total: number; closed: number; open: number;
  by_client: Group[]; by_project: Group[]; by_editor: Group[]; by_root_cause: Group[];
  by_error_category: Group[]; by_action_status: Group[]; by_month: Group[];
}
export interface EscRow {
  id: number; client: string; project: string; job_id: string | null; raised_date: string | null; editor: string | null;
  qc_member: string | null; client_feedback: string | null; root_cause: string | null; error_category: string | null;
  corrective_action: string | null; preventive_action: string | null; action_status: string;
  action_owner: string | null; closed_date: string | null; remarks: string | null;
}

export interface SyncLogRow {
  id: number; trigger: string; status: string; started_at: string; finished_at: string | null;
  files_total: number | null; files_scanned: number; files_changed: number; rows_upserted: number;
  rows_rejected: number; error_text: string | null; progress_pct?: number;
}
export interface HealthResp {
  forms_total: number; checks: { key: string; label: string; count: number; pct: number }[];
  last_sync: SyncLogRow | null; last_successful_sync: SyncLogRow | null;
  issues_last_sync: { type: string; severity: string; count: number }[];
  extra_columns: { kind: string; header: string; rows: number; tabs: number }[]; header_repairs: string[];
  unmapped_columns: string[]; unmapped_statuses: string[]; files_with_errors: { id: number; name: string }[];
}
export interface SyncStatus {
  running: boolean; data_source: string; last: SyncLogRow | null; last_change: SyncLogRow | null;
  heartbeat: { checked_at: string; files_total: number; files_changed: number; status: string } | null;
  auto_sync: { enabled: boolean; interval_minutes: number | null };
}

export interface DocRow {
  id: number; name: string; year: number | null; quarter: number | null; client: string | null; project: string | null;
  status: string; drive_url: string; modified_time: string | null; last_synced_at: string | null; tabs: number; tabs_read: number;
  forms: number; escalations: number; rows_loaded: number; rows_rejected: number; rows_placeholder: number; issues: number;
}
export interface DocsResp { total: number; page: number; page_size: number; totals: { forms: number; escalations: number }; rows: DocRow[] }
export interface DocTab {
  id: number; tab: string; kind: string; counts_in_totals: boolean; month: string | null; header_row: number | null;
  rows_seen: number; rows_loaded: number; rows_rejected: number; rows_placeholder: number; rows_duplicate: number;
  forms: number; escalations: number; note: string | null; browsable: boolean;
}
export interface TabRowsResp {
  tab: string; kind: string; header: string[]; total: number; page: number; page_size: number;
  rows: { row_no: number; cells: string[] }[];
}
export interface CoverageResp {
  files: number; tabs: number; raw_rows_stored: number; forms_from_supplementary_tabs: number;
  kinds: { kind: string; tabs: number; rows_seen: number; rows_loaded: number; note: string | null }[];
  tabs_never_read: { file: string; tab: string }[];
}
export interface DocDetail {
  id: number; name: string; year: number | null; quarter: number | null; client: string | null; status: string; drive_url: string;
  modified_time: string | null; last_synced_at: string | null;
  summary: { forms: number; first_received: string | null; last_received: string | null; editors: number; projects: number; with_qc: number; processed: number; duplicates: number };
  ops_statuses: { status: string; count: number }[]; projects: { project: string; forms: number }[];
  tabs: DocTab[]; issue_types: { type: string; severity: string; count: number }[];
  issues: { severity: string; type: string; row_no: number | null; detail: string | null; tab: string | null }[];
}

// ---- Overall page: forms inside projects, and what pulled a month down
export interface FormsCompareForm { form: string; received: Change; edited: Change; qc_completed: Change; pending_editing: Change }
export interface FormsCompareProject {
  project_id: number; project: string; client: string; form_count: number; forms: FormsCompareForm[];
  received: Change; edited: Change; qc_completed: Change; pending_editing: Change;
}
export interface FormsCompareResp {
  vs: "previous" | "yoy"; partial: boolean; current: Period; previous: Period; definition: string;
  projects: FormsCompareProject[];
}

export interface DriverForm { form: string; current: number; previous: number; delta: number }
export interface DriverProject {
  project_id: number; project: string; client: string; current: number; previous: number; net_delta: number;
  delta: number; form_count: number; forms: DriverForm[]; share_of_decline_pct?: number;
}
export interface DriverMonth {
  month: string; previous_month: string; partial: boolean; current: number; previous: number; delta: number;
  pct_change: number | null; direction: "up" | "down" | "flat";
  decliners: DriverProject[]; decliner_count: number; gainers: DriverProject[]; gainer_count: number;
}
export interface MonthDriversResp { metric: string; definition: string; months: DriverMonth[] }

export interface FormsMonthsForm { form: string; months: number[]; total: number }
export interface FormsMonthsProject { project_id: number; project: string; client: string; months: number[]; total: number; form_count: number; forms: FormsMonthsForm[] }
export interface FormsMonthsResp {
  metric: string; definition: string; months: string[]; partial_month: string | null; totals: number[]; projects: FormsMonthsProject[];
}

export interface DriverRow { project_id: number; project: string; client?: string; form: string; current: number; previous: number; delta: number }
export interface ChangeDriversResp {
  metric: string; definition: string; delta: number;
  current: { from: string; to: string; total: number }; previous: { from: string; to: string; total: number };
  decliners: DriverRow[]; decliner_count: number; decline_total: number;
  gainers: DriverRow[]; gainer_count: number; gain_total: number;
}
