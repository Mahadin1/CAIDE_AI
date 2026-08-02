export type UploadStatus = "pending" | "processing" | "done" | "failed";
export type Plan = "free" | "pro";

export interface Profile {
  id: string;
  email: string;
  plan: Plan;
  reports_this_month: number;
  created_at: string;
}

export interface Upload {
  id: string;
  user_id: string;
  filename: string;
  storage_path: string;
  status: UploadStatus;
  created_at: string;
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

export interface Summary {
  shape: { rows: number; columns: number };
  dtypes: Record<string, string>;
  missing: Record<string, number>;
  missing_pct: Record<string, number>;
  numeric_stats: Record<string, Record<string, number | null>>;
  correlations: Record<string, Record<string, number | null>>;
  outliers: Record<string, OutlierInfo>;
  categorical_summary: Record<string, CategoricalSummary>;
}

export interface Report {
  id: string;
  upload_id: string;
  summary_json: Summary;
  narrative: string;
  created_at: string;
}

export interface Subscription {
  user_id: string;
  paddle_subscription_id: string | null;
  status: "active" | "inactive" | "cancelled";
  updated_at: string;
}
