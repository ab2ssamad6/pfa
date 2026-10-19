// Mirrors backend/app/api/schemas.py
export type IncidentStatus = "open" | "acknowledged" | "resolved";
export type Severity = "low" | "medium" | "high" | "critical";

export interface SourceHealth {
  source: string;
  state: "up" | "degraded" | "down";
  last_ok_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  updated_at: string | null;
}

export interface Health {
  status: "ok" | "degraded" | "down";
  database: boolean;
  source: SourceHealth | null;
  model: { version: string; algorithm: string; threshold: number; loaded_at: string | null } | null;
  worker_last_cycle: string | null;
  worker_stale: boolean;
}

export interface Overview {
  hosts: number;
  incidents_open: number;
  incidents_acknowledged: number;
  incidents_resolved_24h: number;
  windows_last_15m: number;
  anomalies_last_15m: number;
  latest_window_at: string | null;
  pipeline_lag_seconds: number | null;
  health: Health;
}

export interface Host {
  id: number;
  source_ref: string;
  name: string;
  display_name: string;
  criticality: string;
  tags: Record<string, string>;
  active: boolean;
}

export interface HostStatus extends Host {
  last_window_at: string | null;
  last_p_attack: number | null;
  active_incidents: number;
  anomalies_last_15m: number;
}

export interface ScorePoint { ts: string; p_attack: number; is_anomaly: boolean; category: string | null }
export interface MetricSeries {
  item_id: number; key: string; name: string; units: string;
  points: { ts: string; value: number }[];
}

export interface Anomaly {
  window_id: number; host_id: number; host_name: string; ts: string; p_attack: number;
  category: string; category_proba: Record<string, number>; incident_id: number | null;
}

export interface Incident {
  id: number; host_id: number; host_name: string; status: IncidentStatus; severity: Severity;
  category: string; category_counts: Record<string, number>; opened_at: string; last_seen_at: string;
  resolved_at: string | null; resolution: string | null; acknowledged_at: string | null;
  anomaly_count: number; max_score: number; mean_score: number; note: string | null; linked_events: number;
}

export interface ExternalEvent {
  id: number; source_ref: string; host_id: number | null; host_name: string | null; name: string;
  severity: number; clock: string; recovered_at: string | null; tags: Record<string, string>;
}

export interface IncidentDetail extends Incident {
  anomalies: Anomaly[]; events: ExternalEvent[]; timeline: ScorePoint[];
}

export interface Page<T> { total: number; items: T[] }

export interface BinaryMetrics {
  threshold: number; precision: number; recall: number; fpr: number; f1: number;
  roc_auc?: number; pr_auc_attack?: number; pr_auc_benign?: number; brier: number;
  precision_at_10pct_attack_prevalence?: number; tp: number; fp: number; fn: number; tn: number;
}
export interface MulticlassMetrics {
  macro_f1: number; weighted_f1: number; accuracy: number;
  per_class: Record<string, { precision: number; recall: number; f1: number; support: number }>;
  confusion_matrix: { labels: string[]; matrix: number[][] };
}
export interface EvalBlock { n: number; binary: BinaryMetrics; multiclass: MulticlassMetrics; inference_us_per_row: number }

export interface ModelInfo {
  version: string; algorithm: string; threshold: number; threshold_rule: string | null;
  features: string[]; categories: string[]; loaded_at: string | null; calibration: string | null;
  training: Record<string, unknown>; validation: EvalBlock; test: EvalBlock;
}

export interface LiveAccuracy {
  window_minutes: number; evaluated: number; tp: number; fp: number; fn: number; tn: number;
  precision: number | null; recall: number | null; fpr: number | null; note: string;
}
