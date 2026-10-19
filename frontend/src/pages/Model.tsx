import { useLiveAccuracy, useModel } from "../api/hooks";
import type { EvalBlock } from "../api/types";
import { ApiError } from "../api/client";
import { fmtTime, pct } from "../components/format";
import { QueryView } from "../components/StateViews";

function Metric({ label, value }: { label: string; value: string }) {
  return <div><p className="text-xs text-slate-500">{label}</p><p className="text-lg font-semibold">{value}</p></div>;
}

function Confusion({ block }: { block: EvalBlock }) {
  const { labels, matrix } = block.multiclass.confusion_matrix;
  return (
    <div className="overflow-x-auto">
      <table className="text-xs" aria-label="confusion matrix">
        <thead>
          <tr><th className="p-1 text-left text-slate-500">true \ pred</th>{labels.map((l) => <th key={l} className="p-1 text-slate-500">{l}</th>)}</tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => {
            const total = row.reduce((a, b) => a + b, 0) || 1;
            return (
              <tr key={labels[i]}>
                <th className="p-1 text-left font-medium text-slate-600">{labels[i]}</th>
                {row.map((v, j) => {
                  const r = v / total;
                  return (
                    <td key={j} title={`${v} windows`} className="p-1 text-center"
                      style={{ background: `rgba(79,70,229,${r.toFixed(2)})`, color: r > 0.5 ? "white" : "#334155" }}>
                      {(r * 100).toFixed(0)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1 text-xs text-slate-500">Row-normalised % on the held-out test split.</p>
    </div>
  );
}

function LivePanel() {
  const q = useLiveAccuracy(15);
  if (q.error instanceof ApiError && q.error.status === 404) {
    return <p className="text-sm text-slate-500">Live accuracy is disabled (DEMO_TRUTH_URL not configured).</p>;
  }
  return (
    <QueryView q={q} isEmpty={(d) => d.evaluated === 0} empty="No windows to compare yet.">
      {(d) => (
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-3">
            <Metric label="Recall" value={pct(d.recall)} />
            <Metric label="Precision" value={pct(d.precision)} />
            <Metric label="False-positive rate" value={pct(d.fpr, 2)} />
          </div>
          <p className="text-xs text-slate-500">{d.evaluated} windows in the last {d.window_minutes} min · TP {d.tp} · FP {d.fp} · FN {d.fn} · TN {d.tn}. {d.note}</p>
        </div>
      )}
    </QueryView>
  );
}

export default function ModelPage() {
  const q = useModel();
  return (
    <QueryView q={q}>
      {(m) => {
        const t = m.test;
        return (
          <div className="space-y-4">
            <div className="card">
              <h1 className="text-lg font-semibold">Active model: {m.version}</h1>
              <p className="text-sm text-slate-500">
                {m.algorithm} · {m.features.length} features · threshold {m.threshold.toFixed(4)} ({m.threshold_rule}) · calibration: {m.calibration} · loaded {fmtTime(m.loaded_at)}
              </p>
            </div>
            <div className="card">
              <h2 className="mb-3 text-sm font-semibold text-slate-700">Offline test results (binary: attack vs benign, {t.n.toLocaleString()} unique windows)</h2>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-7">
                <Metric label="Recall" value={pct(t.binary.recall, 2)} />
                <Metric label="False-positive rate" value={pct(t.binary.fpr, 2)} />
                <Metric label="Precision" value={pct(t.binary.precision, 2)} />
                <Metric label="Precision @10% prevalence" value={pct(t.binary.precision_at_10pct_attack_prevalence, 1)} />
                <Metric label="ROC-AUC" value={t.binary.roc_auc?.toFixed(4) ?? "—"} />
                <Metric label="PR-AUC (benign)" value={t.binary.pr_auc_benign?.toFixed(4) ?? "—"} />
                <Metric label="8-class macro-F1" value={t.multiclass.macro_f1.toFixed(3)} />
              </div>
              <p className="mt-3 text-xs text-slate-500">
                The dataset is 95% attack traffic; "precision @10% prevalence" re-weights to a benign-majority network, which is closer to production.
              </p>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="card overflow-x-auto">
                <h2 className="mb-2 text-sm font-semibold text-slate-700">Per-category results (test)</h2>
                <table className="min-w-full text-sm">
                  <thead><tr>{["Category", "Precision", "Recall", "F1", "Support"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                  <tbody>
                    {Object.entries(t.multiclass.per_class).map(([k, v]) => (
                      <tr key={k}>
                        <td className="td font-medium">{k}</td><td className="td">{pct(v.precision)}</td>
                        <td className="td">{pct(v.recall)}</td><td className="td">{v.f1.toFixed(3)}</td>
                        <td className="td">{v.support.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="card"><h2 className="mb-2 text-sm font-semibold text-slate-700">Confusion matrix</h2><Confusion block={t} /></div>
            </div>
            <div className="card">
              <h2 className="mb-2 text-sm font-semibold text-slate-700">Live agreement with the demo scenario (ground truth from the mock)</h2>
              <LivePanel />
            </div>
          </div>
        );
      }}
    </QueryView>
  );
}
