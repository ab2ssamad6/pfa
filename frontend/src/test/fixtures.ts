import type { Health, Incident, IncidentDetail, ModelInfo, Overview, HostStatus } from "../api/types";

export const health: Health = {
  status: "ok", database: true,
  source: { source: "zabbix", state: "up", last_ok_at: "2026-10-18T10:00:00Z", last_error: null, consecutive_failures: 0, updated_at: null },
  model: { version: "random_forest-1", algorithm: "random_forest", threshold: 0.8635, loaded_at: null },
  worker_last_cycle: "2026-10-18T10:00:00Z", worker_stale: false,
};

export const overview: Overview = {
  hosts: 3, incidents_open: 1, incidents_acknowledged: 0, incidents_resolved_24h: 2, windows_last_15m: 1350,
  anomalies_last_15m: 40, latest_window_at: "2026-10-18T10:00:00Z", pipeline_lag_seconds: 2.4, health,
};

export const hosts: HostStatus[] = [
  { id: 1, source_ref: "10542", name: "pfsense-edge", display_name: "pfSense Edge Firewall", criticality: "critical", tags: {},
    active: true, last_window_at: "2026-10-18T10:00:00Z", last_p_attack: 0.97, active_incidents: 1, anomalies_last_15m: 40 },
];

export const incident: Incident = {
  id: 7, host_id: 1, host_name: "pfSense Edge Firewall", status: "open", severity: "critical", category: "DDoS",
  category_counts: { DDoS: 77, DoS: 6 }, opened_at: "2026-10-18T09:55:00Z", last_seen_at: "2026-10-18T09:58:00Z",
  resolved_at: null, resolution: null, acknowledged_at: null, anomaly_count: 83, max_score: 1, mean_score: 0.97,
  note: null, linked_events: 2,
};

export const incidentDetail: IncidentDetail = {
  ...incident,
  anomalies: [{ window_id: 1, host_id: 1, host_name: "pfSense Edge Firewall", ts: "2026-10-18T09:55:00Z", p_attack: 0.99,
               category: "DDoS", category_proba: { DDoS: 0.9, DoS: 0.09, Benign: 0.01 }, incident_id: 7 }],
  events: [{ id: 3, source_ref: "900042", host_id: 1, host_name: "pfSense Edge Firewall", name: "pfSense: Firewall states above 80% of maximum",
             severity: 3, clock: "2026-10-18T09:55:40Z", recovered_at: null, tags: { scope: "capacity" } }],
  timeline: [{ ts: "2026-10-18T09:55:00Z", p_attack: 0.99, is_anomaly: true, category: "DDoS" }],
};

const block = {
  n: 3104653, inference_us_per_row: 4.9,
  binary: { threshold: 0.86, precision: 0.999, recall: 0.9734, fpr: 0.0102, f1: 0.986, roc_auc: 0.9959, pr_auc_attack: 0.9998,
            pr_auc_benign: 0.9113, brier: 0.0113, precision_at_10pct_attack_prevalence: 0.9136, tp: 1, fp: 1, fn: 1, tn: 1 },
  multiclass: { macro_f1: 0.7018, weighted_f1: 0.9, accuracy: 0.9,
                per_class: { Benign: { precision: 0.818, recall: 0.877, f1: 0.846, support: 157455 } },
                confusion_matrix: { labels: ["Benign", "DDoS"], matrix: [[90, 10], [5, 95]] } },
};

export const model: ModelInfo = {
  version: "random_forest-1", algorithm: "random_forest", threshold: 0.8635, threshold_rule: "benign FPR <= 0.01 on validation B",
  features: Array.from({ length: 37 }, (_, i) => `f${i}`), categories: ["Benign", "DDoS"], loaded_at: null,
  calibration: "isotonic", training: {}, validation: block, test: block,
};
