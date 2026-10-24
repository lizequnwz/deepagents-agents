export type Row = Record<string, unknown>;
export interface Source {
  source_id: string;
  name: string;
  description: string;
  ready: boolean;
  errors: string[];
  backend_type: string;
  examples: { label: string; question: string }[];
}
export interface ConversationSummary {
  thread_id: string;
  source_id: string;
  title: string;
  active_run_id: string | null;
  run_ids: string[];
}
export interface Chart {
  chart_id: string;
  title: string;
  result_id: string;
  chart_type: string;
  notes?: string[];
}
export interface Report {
  report_id: string;
  title: string;
  version: number;
  created_at: string;
}
export interface Answer {
  answer: string;
  results: {
    result_id: string;
    short_label: string;
    executed_sql: string;
    originating_question: string;
  }[];
  charts: Chart[];
  assumptions: string[];
  partial: boolean;
  unresolved_questions: string[];
  report: Report | null;
  dashboard?: Dashboard | null;
}
export interface Activity {
  id: number;
  kind: string;
  label: string;
  phase: string;
  agent?: string;
  tool?: { name: string; input?: unknown; output?: unknown };
}
export interface Turn {
  run_id: string;
  user_message: string;
  answer: Answer;
  activities: Activity[];
  created_at: string;
}
export interface Conversation {
  thread_id: string;
  source_id: string;
  turns: Turn[];
  run_ids: string[];
  active_run_id: string | null;
}
export interface ReviewAction {
  action_name: string;
  query: string;
  review_type: "sql" | "python";
  allowed_decisions: ("approve" | "edit" | "reject")[];
  description: string;
  arguments: Row;
  source_id?: string;
  dialect?: string;
  timeout_seconds?: number;
  max_result_rows?: number;
  input_datasets?: Record<
    string,
    {
      result_id: string;
      originating_question: string;
      columns: string[];
      row_count: number;
      truncated: boolean;
      sample_rows: Row[];
    }
  >;
}
export type RunStatus =
  | "queued"
  | "running"
  | "approval_required"
  | "clarification_required"
  | "completed"
  | "failed"
  | "paused"
  | "stopping";
export interface Run {
  run_id: string;
  thread_id: string;
  question: string;
  status: RunStatus;
  phase: string;
  findings: Answer | null;
  answer: Answer | null;
  error: string | null;
  events: Activity[];
  approval: { interrupt_id: string; actions: ReviewAction[] } | null;
  clarification: {
    interrupt_id: string;
    question: string;
    choices: string[];
  } | null;
  report_ready: boolean;
}
export interface Dataset {
  result_id: string;
  label: string;
  row_count: number;
  columns: string[];
  kind: string;
  complete: boolean;
  snapshot_at: string;
  grain: string;
  question: string;
}
export interface ResultPage {
  result_id: string;
  short_label: string;
  columns: string[];
  rows: Row[];
  row_count: number;
  truncated: boolean;
  executed_sql: string;
  offset: number;
  limit: number;
  profile?: unknown;
}
export interface UploadColumn {
  name: string;
  stored_type: string;
  suggested_type: string;
  null_count: number;
  distinct_count: number;
  warning: string;
}
export interface Upload {
  upload_id: string;
  thread_id: string;
  source_id: string;
  filename: string;
  row_count: number;
  columns: UploadColumn[];
  confirmed: boolean;
  sample_rows: Row[];
  warnings: string[];
  review?: {
    types: Record<string, string>;
    grain: string;
    key_columns: string[];
  };
  result_id: string;
}
export interface DocumentRef {
  document_id: string;
  filename: string;
  thread_id: string;
  page_count: number;
  sha256: string;
}
export interface DashboardFilter {
  id: string;
  label: string;
  kind: "category" | "date_range";
  bindings: { component_id: string; column: string }[];
  description?: string;
  default_values?: unknown[];
  options?: unknown[];
  options_truncated?: boolean;
}
export interface DashboardComponent {
  id: string;
  type: string;
  title?: string;
  label?: string;
  chart_id?: string;
  result_id?: string;
  analysis_result_id?: string;
  empty_result_id?: string;
  column?: string;
  row_index?: number;
  value?: unknown;
  formatted_value?: string;
  body?: string;
  rows?: Row[];
  columns?: string[];
  span?: number;
  metric?: Row;
  figure?: { data: unknown[]; layout: Row } | null;
  warnings?: string[];
  notes?: string[];
  row_count?: number;
}
export interface DashboardSpec {
  title: string;
  description?: string;
  components: DashboardComponent[];
  filters: DashboardFilter[];
}
export interface DashboardRevision {
  dashboard_id: string;
  revision_id: string;
  version: number;
  title?: string;
  thread_id: string;
  source_id: string;
  run_id: string;
  report_id: string;
  created_at: string;
  spec: DashboardSpec;
  applied_filters: Record<string, unknown[]>;
  saved_filter_values: Record<string, unknown[]>;
}
export interface Dashboard {
  revision: DashboardRevision;
  components: DashboardComponent[];
  filters: DashboardFilter[];
  freshness: {
    result_id: string;
    queried_at: string;
    completeness: string;
    snapshot_kind: string;
  }[];
  pending_action?: { run_id: string; status?: string; error?: string } | null;
}
