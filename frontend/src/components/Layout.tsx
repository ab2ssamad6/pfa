import { NavLink, Outlet } from "react-router-dom";
import { useHealth } from "../api/hooks";
import { StateDot } from "./Badges";
import { fmtTime } from "./format";

const NAV = [
  ["/", "Overview"], ["/hosts", "Hosts"], ["/incidents", "Incidents"], ["/anomalies", "Anomalies"],
  ["/events", "Zabbix problems"], ["/model", "Model"],
] as const;

export function HealthBanner() {
  const { data, error } = useHealth();
  if (error && !data) {
    return <div role="alert" className="bg-red-600 px-4 py-2 text-sm text-white">API unreachable — data shown may be stale.</div>;
  }
  if (!data || data.status === "ok") return null;
  const reasons: string[] = [];
  if (data.worker_stale) reasons.push(`worker has not completed a cycle since ${fmtTime(data.worker_last_cycle)}`);
  if (data.source && data.source.state !== "up")
    reasons.push(`telemetry source ${data.source.state}: ${data.source.last_error ?? "unknown error"} (last OK ${fmtTime(data.source.last_ok_at)})`);
  if (!data.model) reasons.push("no active model loaded");
  return (
    <div role="alert" className={`px-4 py-2 text-sm ${data.status === "down" ? "bg-red-600 text-white" : "bg-amber-100 text-amber-900"}`}>
      Pipeline {data.status}: {reasons.join("; ") || "see /api/health"}
    </div>
  );
}

export default function Layout() {
  const { data } = useHealth();
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-indigo-700">NetAD</span>
            <span className="hidden text-sm text-slate-500 sm:inline">AI-assisted network anomaly detection · pfSense / Zabbix</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-600">
            <StateDot state={data?.status ?? "down"} /> pipeline {data?.status ?? "unknown"}
            {data?.model && <span className="hidden md:inline">· model {data.model.version}</span>}
          </div>
        </div>
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) =>
                `whitespace-nowrap border-b-2 px-3 py-2 text-sm ${isActive ? "border-indigo-600 font-medium text-indigo-700" : "border-transparent text-slate-600 hover:text-slate-900"}`}>
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <HealthBanner />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-6 text-xs text-slate-400">
        Scores are machine-learning predictions on flow-window features, not confirmed attacks. Demo telemetry is replayed from the CICIoT2023 test split.
      </footer>
    </div>
  );
}
