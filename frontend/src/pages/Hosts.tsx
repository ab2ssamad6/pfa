import { Link, useParams } from "react-router-dom";
import { useState } from "react";
import { useHealth, useHost, useHosts, useIncidents, useMetrics, useScores } from "../api/hooks";
import { SeverityBadge, StatusBadge, Suspected } from "../components/Badges";
import { MetricChart, ScoreChart } from "../components/Charts";
import { fmtTime, score } from "../components/format";
import { QueryView } from "../components/StateViews";

export function HostsPage() {
  const hosts = useHosts();
  return (
    <div className="card overflow-x-auto p-0">
      <QueryView q={hosts} isEmpty={(d) => d.length === 0} empty="No hosts discovered yet.">
        {(hs) => (
          <table className="min-w-full divide-y divide-slate-200">
            <thead><tr>{["Host", "Zabbix host", "Criticality", "Last window", "Latest score", "Anomalies (15m)", "Active incidents"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">
              {hs.map((h) => (
                <tr key={h.id} className={h.active ? "" : "opacity-50"}>
                  <td className="td"><Link className="text-indigo-700 hover:underline" to={`/hosts/${h.id}`}>{h.display_name}</Link></td>
                  <td className="td font-mono text-xs">{h.name} ({h.source_ref})</td>
                  <td className="td">{h.criticality}</td>
                  <td className="td">{fmtTime(h.last_window_at)}</td>
                  <td className="td">{score(h.last_p_attack)}</td>
                  <td className="td">{h.anomalies_last_15m}</td>
                  <td className="td">{h.active_incidents}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryView>
    </div>
  );
}

const RANGES = [15, 30, 60, 180] as const;

export function HostDetailPage() {
  const id = Number(useParams().id);
  const [minutes, setMinutes] = useState<number>(30);
  const host = useHost(id);
  const health = useHealth();
  const scores = useScores(id, minutes);
  const metrics = useMetrics(id, minutes);
  const incidents = useIncidents(undefined, id, 20);
  return (
    <div className="space-y-4">
      <QueryView q={host}>
        {(h) => (
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h1 className="text-xl font-semibold">{h.display_name}</h1>
              <p className="text-sm text-slate-500">{h.name} · Zabbix hostid {h.source_ref} · criticality {h.criticality}</p>
            </div>
            <div className="flex gap-1" role="group" aria-label="time range">
              {RANGES.map((r) => (
                <button key={r} onClick={() => setMinutes(r)} className={r === minutes ? "btn-primary" : "btn-secondary"}>{r}m</button>
              ))}
            </div>
          </div>
        )}
      </QueryView>
      <section className="card">
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Model attack score (red = anomalous window)</h2>
        <QueryView q={scores} isEmpty={(d) => d.length === 0} empty="No scored windows in this range.">
          {(d) => <ScoreChart points={d} threshold={health.data?.model?.threshold} />}
        </QueryView>
      </section>
      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Zabbix metrics (context only — not used by the model)</h2>
        <QueryView q={metrics} isEmpty={(d) => d.length === 0} empty="No numeric items for this host.">
          {(ms) => (
            <div className="grid gap-3 md:grid-cols-2">
              {ms.map((m) => (
                <div key={m.item_id} className="card">
                  <p className="mb-1 text-sm font-medium">{m.name} <span className="font-mono text-xs text-slate-400">{m.key}</span></p>
                  {m.points.length ? <MetricChart series={m} /> : <p className="text-sm text-slate-500">No samples.</p>}
                </div>
              ))}
            </div>
          )}
        </QueryView>
      </section>
      <section className="card p-0">
        <h2 className="px-4 py-3 text-sm font-semibold text-slate-700">Incidents on this host</h2>
        <QueryView q={incidents} isEmpty={(d) => d.items.length === 0} empty="No incidents for this host.">
          {(p) => (
            <ul className="divide-y divide-slate-100">
              {p.items.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
                  <StatusBadge status={i.status} /><SeverityBadge severity={i.severity} />
                  <Link to={`/incidents/${i.id}`} className="text-indigo-700 hover:underline">#{i.id}</Link>
                  <Suspected category={i.category} score={i.max_score} />
                  <span className="ml-auto text-xs text-slate-500">{fmtTime(i.opened_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>
    </div>
  );
}
