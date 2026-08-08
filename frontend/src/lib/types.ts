export type UploadStatus = "pending" | "ready" | "processing" | "done" | "failed";
export type Plan = "free" | "starter" | "pro" | "scale";
export interface Profile {
  id: string;
  email: string;
  name: string | null;
  plan: Plan;
  credits: number;
  reports_this_month: number;
  created_at: string;
}
export interface SampleInfo {
  mode: "full" | "sample" | "truncated";
  total_rows: number;
  sample_rows: number;
  sampled_fraction: number;
  confidence_level: number;
  sampling_method: string;
  seed: number;
  margin_of_error: number;
  interpretation: string;
}
export interface Upload {
  id: string;
  user_id: string;
  filename: string;
  storage_path: string;
  status: UploadStatus;
  created_at: string;
  stage?: string | null;
  stage_label?: string | null;
  progress?: number | null;
  error_message?: string | null;
  file_size_bytes?: number | null;
  source_format?: string | null;
  detected_encoding?: string | null;
  analysis_mode?: "full" | "sample" | "truncated" | null;
  row_estimate?: number | null;
  column_count?: number | null;
  reports?: Report[];
}
export interface OutlierInfo {
  count: number;
  share: number;
  low_bound: number | null;
  high_bound: number | null;
  outlier_sample?: number[];
}
export interface CategoricalSummary {
  cardinality: number;
  total: number;
  top: { value: string; count: number; share: number }[];
}
export type ColumnKind =
  | "numeric"
  | "categorical"
  | "date_like"
  | "mixed"
  | "constant"
  | "identifier"
  | "free_text"
  | "boolean"
  | "empty";

export interface ColumnClassification {
  kind: ColumnKind;
  cardinality: number;
  total: number;
  top_value_share?: number;
  date_parse_rate?: number;
  numeric_share?: number;
  unique_ratio?: number;
}

/** Pre-computed histogram for a numeric column (agent.compute_histograms). */
export interface HistogramInfo {
  bin_edges: number[];
  counts: number[];
}

/** One group's stats within a numeric-by-category comparison. */
export interface GroupStat {
  group: string;
  mean: number;
  median: number;
  count: number;
}

/** A single numeric-column-by-categorical-column comparison
 * (agent.compare_numeric_by_category), keyed as "num__by__cat" in
 * Summary.numeric_by_categorical. */
export interface GroupComparisonEntry {
  numeric_column: string;
  category_column: string;
  groups: GroupStat[];
  effect_size_std: number;
}

/** Association strength between two categorical columns
 * (agent.compute_categorical_associations), keyed as "a__vs__b" in
 * Summary.categorical_associations. */
export interface CategoricalAssociationEntry {
  column_a: string;
  column_b: string;
  cramers_v: number;
}

export interface TimeTrendPoint {
  period: string;
  count: number;
}

/** Monthly row-count trend for a date-like column
 * (agent.compute_time_trends), keyed by column name in
 * Summary.time_trends. */
export interface TimeTrendEntry {
  periods: number;
  start: string;
  end: string;
  trend_correlation: number;
  direction: "increasing" | "decreasing";
  series: TimeTrendPoint[];
}

/** Declarative chart suggestion from agent.build_chart_specs. Not
 * currently rendered directly (ReportCharts uses its own flagging
 * thresholds instead, matching agent.select_findings), but typed here
 * since it's present in summary_json. */
export interface ChartSpec {
  type: "histogram" | "boxplot" | "bar" | "line" | "heatmap" | "scatter" | "grouped_bar";
  columns: string[];
  title: string;
}

export interface Summary {
  shape: { rows: number; columns: number };
  dtypes: Record<string, string>;
  column_classification: Record<string, ColumnClassification>;
  duplicate_count: number;
  duplicate_share: number;
  missing: Record<string, number>;
  missing_pct: Record<string, number>;
  numeric_stats: Record<string, Record<string, number | null>>;
  correlations: Record<string, Record<string, number | null>>;
  outliers: Record<string, OutlierInfo>;
  categorical_summary: Record<string, CategoricalSummary>;
  // Present on reports generated after the agent.py Phase 3 update.
  // Optional so older rows in the `reports` table (generated before this
  // field existed) don't break existing report pages.
  histograms?: Record<string, HistogramInfo>;
  numeric_by_categorical?: Record<string, GroupComparisonEntry>;
  categorical_associations?: Record<string, CategoricalAssociationEntry>;
  time_trends?: Record<string, TimeTrendEntry>;
  chart_specs?: ChartSpec[];
  executed_tasks?: { type: string; description?: string }[];
  skipped_tasks?: { type: string; reason: string }[];
  adaptive?: Record<string, unknown>;
  findings?: ReportFinding[];
}
export interface ReportFinding {
  type: string;
  severity: "info" | "low" | "medium" | "high";
  message: string;
  detail?: string;
  action?: string;
}
export interface Report {
  id: string;
  upload_id: string;
  summary_json: Summary;
  narrative: string;
  created_at: string;
  analysis_mode?: "full" | "sample" | "truncated" | null;
  source_format?: string | null;
  analysis_plan_json?: { tasks?: PlanTask[]; source?: string } | null;
  overrides_json?: Record<string, unknown> | null;
  sample_info_json?: SampleInfo | null;
  export_html_url?: string | null;
  export_pdf_url?: string | null;
  cleaned_data_url?: string | null;
}
export interface PlanTask {
  id: string;
  type: string;
  description: string;
  rationale: string;
  target_columns: string[];
  enabled: boolean;
}
/** Response from POST /api/analyze/plan (plan-preview step). */
export interface PlanPreview {
  job_id: string;
  fingerprint: Record<string, unknown>;
  plan: { tasks: PlanTask[]; source: "llm" | "fallback" | "cache" };
  column_types: Record<string, ColumnKind>;
  overview: {
    format: string;
    encoding: string;
    mode: "full" | "sample" | "truncated";
    sample_info: SampleInfo;
    shape: { rows: number; total_rows: number; columns: number };
  };
}
/** Response from GET /api/jobs/:id (polling). */
export interface JobStatus {
  job_id: string;
  status: UploadStatus;
  stage: string | null;
  stage_label: string | null;
  progress: number;
  error_message: string | null;
  source_format: string | null;
  analysis_mode: "full" | "sample" | "truncated" | null;
  report_id: string | null;
}
export interface Subscription {
  user_id: string;
  paddle_subscription_id: string | null;
  status: "active" | "inactive" | "cancelled";
  updated_at: string;
}
