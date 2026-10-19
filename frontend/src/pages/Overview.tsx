import { Link } from "react-router-dom";
import { useHealth, useHosts, useIncidents, useOverview, useScores } from "../api/hooks";
import type { HostStatus } from "../api/types";
import { SeverityBadge, StateDot, StatusBadge, Suspected } from "../components/Badges";
import { ScoreChart } from "../components/Charts";
import { fmtDuration, fmtTime, score } from "../components/format";
import { Empty, QueryView } from "../components/StateViews";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="card">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

function HostScoreCard({ host, threshold }: { host: HostStatus; threshold?: number }) {
  const scores = useScores(host.id, 15);
  return (
    <div className="card">
      <div className="mb-2 flex items-center justify-between">
        <Link to={`/hosts/${host.id}`} className="font-medium text-indigo-700 hover:underline">{host.display_name}</Link>
        <span className="text-xs text-slate-500">
          {host.active_incidents > 0 ? <span className="font-semibold text-red-600">{host.active_incidents} active incident(s)</span> : "no active incident"}
          {" · "}latest score {score(host.last_p_attack)}
        </span>
      </div>
      <QueryView q={scores} isEmpty={(d) => d.length === 0} empty="No scored telemetry yet.">
        {(d) => <ScoreChart points={d} threshold={threshold} height={140} />}
      </QueryView>
    </div>
  );
}

export default function OverviewPage() {
  const ov = useOverview();
  const hosts = useHosts();
  const health = useHealth();
  const active = useIncidents(undefined, undefined, 8);
  const threshold = health.data?.model?.threshold;
  return (
    <div className="space-y-6">
      <QueryView q={ov}>
        {(o) => (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Stat label="Monitored hosts" value={o.hosts} />
            <Stat label="Open incidents" value={o.incidents_open} />
            <Stat label="Acknowledged" value={o.incidents_acknowledged} />
            <Stat label="Resolved (24h)" value={o.incidents_resolved_24h} />
            <Stat label="Anomalous windows (15 min)" value={o.anomalies_last_15m} hint={`of ${o.windows_last_15m} windows scored`} />
            <div className="card">
              <p className="text-xs uppercase tracking-wide text-slate-500">Telemetry source</p>
              <p className="mt-1 flex items-center gap-2 text-lg font-semibold">
                <StateDot state={o.health.source?.state ?? "down"} /> {o.health.source?.state ?? "unknown"}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                lag {o.pipeline_lag_seconds === null ? "—" : `${o.pipeline_lag_seconds.toFixed(1)} s`}
              </p>
            </div>
          </div>
        )}
      </QueryView>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Attack score per host (last 15 min of telemetry)</h2>
        <QueryView q={hosts} isEmpty={(d) => d.length === 0} empty="No hosts discovered yet — waiting for the worker's first inventory sync.">
          {(hs) => (
            <div className="grid gap-3 lg:grid-cols-3">
              {hs.map((h) => <HostScoreCard key={h.id} host={h} threshold={threshold} />)}
            </div>
          )}
        </QueryView>
      </section>

      <section className="card p-0">
        <div className="flex items-center justify-between px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-700">Recent incidents</h2>
          <Link to="/incidents" className="text-sm text-indigo-700 hover:underline">All incidents →</Link>
        </div>
        <QueryView q={active} isEmpty={(d) => d.items.length === 0} empty="No incidents detected.">
          {(page) => (
            <ul className="divide-y divide-slate-100">
              {page.items.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
                  <StatusBadge status={i.status} />
                  <SeverityBadge severity={i.severity} />
                  <Link to={`/incidents/${i.id}`} className="text-indigo-700 hover:underline">#{i.id}</Link>
                  <Suspected category={i.category} score={i.max_score} />
                  <span className="text-slate-500">on {i.host_name}</span>
                  <span className="ml-auto text-xs text-slate-500">{fmtTime(i.opened_at)} · {fmtDuration(i.opened_at, i.resolved_at ?? i.last_seen_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>
      {ov.data && ov.data.hosts === 0 && <Empty>Start the stack with ./scripts/start.sh — telemetry appears within seconds.</Empty>}
    </div>
  );
}
