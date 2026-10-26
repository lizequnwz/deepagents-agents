/* Generated from DashboardView. Run npm run generate:dashboard. Do not edit. */

export type DashboardId = string;
export type RevisionId = string;
export type Version = number;
export type ThreadId = string;
export type SourceId = string;
export type RunId = string;
export type ReportId = string | null;
export type Question = string;
export type SchemaVersion = "1.0";
export type Title = string;
export type Description = string;
export type Id = string;
export type Span = 1 | 2 | 3;
export type Type = "metric";
export type Label = string;
export type ResultId = string;
export type Column = string;
export type RowIndex = number;
/**
 * One Python numeric format such as ,.2f or +,.2f; not Excel sections or D3 patterns.
 */
export type NumberFormat = string;
export type Prefix = string;
export type Suffix = string;
/**
 * Exact semantic metric name, or reviewed upload measure name.
 */
export type MetricRef = string;
/**
 * Shared population and filters of this one saved snapshot.
 */
export type Population = string;
/**
 * Columns uniquely identifying each aggregate row, including the period column.
 *
 * @minItems 1
 */
export type Grain = string[];
export type PeriodColumn = string;
export type CurrentPeriod = string;
export type BaselinePeriod = string;
export type BaselineRowIndex = number;
/**
 * Saved unit/currency label column. Omit when units are unspecified; no currency will be inferred.
 */
export type UnitColumn = string | null;
export type NumeratorColumn = string | null;
/**
 * For an already computed rate/share, name the saved denominator column; values are disclosed, never silently recomputed.
 */
export type DenominatorColumn = string | null;
export type RateScale = 1 | 100;
export type Completeness = "unknown";
export type Context = string | null;
export type Id1 = string;
export type Span1 = 1 | 2 | 3;
export type Type1 = "chart";
export type ChartId = string | null;
export type EmptyResultId = string | null;
export type Title1 = string | null;
export type Id2 = string;
export type Span2 = 1 | 2 | 3;
export type Type2 = "table";
export type ResultId1 = string;
export type Title2 = string;
/**
 * @maxItems 40
 */
export type Columns = string[];
export type RowLimit = number;
export type Id3 = string;
export type Span3 = 1 | 2 | 3;
export type Type3 = "text";
export type Title3 = string | null;
export type Body = string;
/**
 * @minItems 1
 * @maxItems 60
 */
export type Components = (MetricComponent | ChartComponent | TableComponent | TextComponent)[];
export type Id4 = string;
export type Label1 = string;
export type Kind = "category" | "date_range";
export type Description1 = string;
export type ComponentId = string;
export type Column1 = string;
/**
 * @minItems 1
 * @maxItems 60
 */
export type Bindings = FilterBinding[];
/**
 * @maxItems 100
 */
export type DefaultValues = (string | number | boolean | null)[];
/**
 * @maxItems 12
 */
export type Filters = DashboardFilter[];
export type CreatedAt = string;
export type Id5 = string;
export type Type4 = "metric" | "chart" | "table" | "text";
export type Title4 = string;
export type Span4 = number;
export type FormattedValue = string | null;
export type Data = {
  [k: string]: unknown;
}[];
export type Rows =
  | {
      [k: string]: unknown;
    }[]
  | null;
export type Columns1 = string[] | null;
export type Body1 = string | null;
export type ResultId2 = string | null;
export type AnalysisResultId = string | null;
export type ChartId1 = string | null;
export type RowCount = number | null;
export type Truncated = boolean;
export type Warnings = string[];
export type Notes = string[];
export type Column2 = string;
export type Label2 = string;
export type PointKey = "x" | "y" | "label" | "name";
export type SelectionFields = ChartSelectionField[];
export type Components1 = ResolvedComponent[];
export type Id6 = string;
export type Label3 = string;
export type Kind1 = "category" | "date_range";
export type Description2 = string;
/**
 * @minItems 1
 * @maxItems 60
 */
export type Bindings1 = FilterBinding[];
/**
 * @maxItems 100
 */
export type DefaultValues1 = (string | number | boolean | null)[];
export type Options = (string | number | boolean | null)[];
export type OptionsTruncated = boolean;
export type Filters1 = ResolvedFilter[];
export type ResultId3 = string;
export type QueriedAt = string;
export type Completeness1 = "unknown";
export type SnapshotKind = string;
export type Truncated1 = boolean;
export type Freshness = DashboardFreshness[];
export type ActionId = string;
export type DashboardId1 = string;
export type RevisionId1 = string;
export type RequestId = string;
export type RequestHash = string;
export type Action = "filter" | "refresh" | "drill";
export type ExpectedRevision = string;
export type RequestId1 = string;
export type ComponentId1 = string | null;
export type Question1 = string | null;
export type ResultId4 = string;
export type Column3 = string;
/**
 * @minItems 1
 * @maxItems 100
 */
export type Values = (string | number | boolean | null)[];
export type RunId1 = string | null;
export type Status = "queued" | "running" | "completed" | "failed";
export type ResultRevisionId = string | null;
export type Error = string | null;
export type CreatedAt1 = string;

export interface DashboardView {
  revision: DashboardRevision;
  components: Components1;
  filters: Filters1;
  freshness: Freshness;
  pending_action: DashboardActionRecord | null;
}
export interface DashboardRevision {
  dashboard_id: DashboardId;
  revision_id: RevisionId;
  version: Version;
  thread_id: ThreadId;
  source_id: SourceId;
  run_id: RunId;
  report_id: ReportId;
  question: Question;
  spec: DashboardSpec;
  applied_filters: AppliedFilters;
  saved_filter_values: SavedFilterValues;
  created_at: CreatedAt;
}
export interface DashboardSpec {
  schema_version: SchemaVersion;
  title: Title;
  description: Description;
  components: Components;
  filters: Filters;
}
export interface MetricComponent {
  id: Id;
  span: Span;
  type: Type;
  metric: ReportMetric;
}
export interface ReportMetric {
  label: Label;
  result_id: ResultId;
  column: Column;
  row_index?: RowIndex;
  number_format?: NumberFormat;
  prefix?: Prefix;
  suffix?: Suffix;
  comparison?: PeriodComparison | null;
  context?: Context;
}
export interface PeriodComparison {
  metric_ref: MetricRef;
  population: Population;
  grain: Grain;
  period_column: PeriodColumn;
  current_period: CurrentPeriod;
  baseline_period: BaselinePeriod;
  baseline_row_index: BaselineRowIndex;
  unit_column?: UnitColumn;
  numerator_column?: NumeratorColumn;
  denominator_column?: DenominatorColumn;
  rate_scale?: RateScale;
  completeness?: Completeness;
}
export interface ChartComponent {
  id: Id1;
  span: Span1;
  type: Type1;
  chart_id: ChartId;
  empty_result_id: EmptyResultId;
  title: Title1;
}
export interface TableComponent {
  id: Id2;
  span: Span2;
  type: Type2;
  result_id: ResultId1;
  title: Title2;
  columns: Columns;
  row_limit: RowLimit;
}
export interface TextComponent {
  id: Id3;
  span: Span3;
  type: Type3;
  title: Title3;
  body: Body;
}
export interface DashboardFilter {
  id: Id4;
  label: Label1;
  kind: Kind;
  description: Description1;
  bindings: Bindings;
  default_values: DefaultValues;
}
export interface FilterBinding {
  component_id: ComponentId;
  column: Column1;
}
export interface AppliedFilters {
  [k: string]: (string | number | boolean | null)[];
}
export interface SavedFilterValues {
  [k: string]: (string | number | boolean | null)[];
}
export interface ResolvedComponent {
  id: Id5;
  type: Type4;
  title: Title4;
  span: Span4;
  value: unknown;
  formatted_value: FormattedValue;
  figure: PlotlyFigure | null;
  rows: Rows;
  columns: Columns1;
  body: Body1;
  result_id: ResultId2;
  analysis_result_id: AnalysisResultId;
  chart_id: ChartId1;
  row_count: RowCount;
  truncated: Truncated;
  warnings: Warnings;
  notes: Notes;
  selection_fields: SelectionFields;
}
export interface PlotlyFigure {
  data: Data;
  layout: Layout;
}
export interface Layout {
  [k: string]: unknown;
}
export interface ChartSelectionField {
  column: Column2;
  label: Label2;
  point_key: PointKey;
}
export interface ResolvedFilter {
  id: Id6;
  label: Label3;
  kind: Kind1;
  description: Description2;
  bindings: Bindings1;
  default_values: DefaultValues1;
  options: Options;
  options_truncated: OptionsTruncated;
}
export interface DashboardFreshness {
  result_id: ResultId3;
  queried_at: QueriedAt;
  completeness: Completeness1;
  snapshot_kind: SnapshotKind;
  truncated: Truncated1;
}
export interface DashboardActionRecord {
  action_id: ActionId;
  dashboard_id: DashboardId1;
  revision_id: RevisionId1;
  request_id: RequestId;
  request_hash: RequestHash;
  action: DashboardAction;
  run_id: RunId1;
  status: Status;
  result_revision_id: ResultRevisionId;
  error: Error;
  created_at: CreatedAt1;
}
export interface DashboardAction {
  action: Action;
  expected_revision: ExpectedRevision;
  request_id: RequestId1;
  filter_values: FilterValues;
  component_id: ComponentId1;
  question: Question1;
  selection: ChartSelection | null;
}
export interface FilterValues {
  [k: string]: (string | number | boolean | null)[];
}
export interface ChartSelection {
  result_id: ResultId4;
  column: Column3;
  values: Values;
}
