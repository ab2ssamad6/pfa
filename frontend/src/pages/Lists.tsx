import { useState } from "react";
import { Link } from "react-router-dom";
import { useAnomalies, useEvents } from "../api/hooks";
import { fmtTime, ZABBIX_SEVERITY } from "../components/format";
import { QueryView } from "../components/StateViews";

export function AnomaliesPage() {
  const q = useAnomalies(undefined, 200);
  return (
    <div className="card overflow-x-auto p-0">
      <p className="px-4 py-3 text-sm text-slate-600">
        Individual windows whose attack score crossed the model threshold. Isolated anomalies that do not pass the 3-of-5 debounce never become incidents.
      </p>
      <QueryView q={q} isEmpty={(d) => d.items.length === 0} empty="No anomalous windows yet.">
        {(p) => (
          <table className="min-w-full divide-y divide-slate-200">
            <thead><tr>{["Time", "Host", "Score", "Suspected category", "Incident"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">
              {p.items.map((a) => (
                <tr key={a.window_id}>
                  <td className="td">{fmtTime(a.ts)}</td>
                  <td className="td">{a.host_name}</td>
                  <td className="td">{a.p_attack.toFixed(3)}</td>
                  <td className="td">{a.category}</td>
                  <td className="td">{a.incident_id ? <Link className="text-indigo-700 hover:underline" to={`/incidents/${a.incident_id}`}>#{a.incident_id}</Link> : <span className="text-slate-400">isolated</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryView>
    </div>
  );
}

export function EventsPage() {
  const [activeOnly, setActiveOnly] = useState(false);
  const q = useEvents(activeOnly);
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} /> Only open problems
      </label>
      <div className="card overflow-x-auto p-0">
        <p className="px-4 py-3 text-sm text-slate-600">Problems raised by Zabbix triggers (rule-based). They are shown separately from ML incidents and only linked when they overlap.</p>
        <QueryView q={q} isEmpty={(d) => d.length === 0} empty="No Zabbix problems.">
          {(evs) => (
            <table className="min-w-full divide-y divide-slate-200">
              <thead><tr>{["Raised", "Host", "Problem", "Severity", "Recovered", "Tags"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-slate-100">
                {evs.map((e) => (
                  <tr key={e.id}>
                    <td className="td">{fmtTime(e.clock)}</td>
                    <td className="td">{e.host_name ?? "—"}</td>
                    <td className="td">{e.name}</td>
                    <td className="td">{ZABBIX_SEVERITY[e.severity] ?? e.severity}</td>
                    <td className="td">{e.recovered_at ? fmtTime(e.recovered_at) : <span className="font-medium text-red-600">open</span>}</td>
                    <td className="td text-xs text-slate-500">{Object.entries(e.tags).map(([k, v]) => `${k}=${v}`).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryView>
      </div>
    </div>
  );
}
