import type { IncidentStatus, Severity } from "../api/types";

const SEV: Record<Severity, string> = {
  low: "bg-slate-100 text-slate-700",
  medium: "bg-amber-100 text-amber-800",
  high: "bg-orange-100 text-orange-800",
  critical: "bg-red-100 text-red-800",
};
const STATUS: Record<IncidentStatus, string> = {
  open: "bg-red-50 text-red-700 ring-red-200",
  acknowledged: "bg-amber-50 text-amber-700 ring-amber-200",
  resolved: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};

export const SeverityBadge = ({ severity }: { severity: Severity }) => (
  <span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ${SEV[severity]}`}>{severity}</span>
);

export const StatusBadge = ({ status }: { status: IncidentStatus }) => (
  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${STATUS[status]}`}>{status}</span>
);

export function StateDot({ state }: { state: "up" | "degraded" | "down" | "ok" | string }) {
  const c = state === "up" || state === "ok" ? "bg-emerald-500" : state === "degraded" ? "bg-amber-500" : "bg-red-500";
  return <span aria-label={state} className={`inline-block h-2.5 w-2.5 rounded-full ${c}`} />;
}

/** Model output wording: always "suspected", never presented as a confirmed attack. */
export function Suspected({ category, score }: { category: string; score: number }) {
  return (
    <span title="Machine-learning prediction — requires analyst confirmation">
      Suspected <strong>{category}</strong> <span className="text-slate-500">(score {score.toFixed(2)})</span>
    </span>
  );
}
