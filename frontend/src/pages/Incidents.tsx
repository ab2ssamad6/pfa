import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useHealth, useIncident, useIncidentAction, useIncidents } from "../api/hooks";
import type { IncidentStatus } from "../api/types";
import { SeverityBadge, StatusBadge, Suspected } from "../components/Badges";
import { CategoryBars, ScoreChart } from "../components/Charts";
import { fmtDuration, fmtTime, ZABBIX_SEVERITY } from "../components/format";
import { ErrorState, QueryView } from "../components/StateViews";

const FILTERS: (IncidentStatus | undefined)[] = [undefined, "open", "acknowledged", "resolved"];
const PAGE = 25;

export function IncidentsPage() {
  const [status, setStatus] = useState<IncidentStatus | undefined>("open");
  const [offset, setOffset] = useState(0);
  const q = useIncidents(status, undefined, PAGE, offset);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1" role="tablist">
        {FILTERS.map((f) => (
          <button key={f ?? "all"} role="tab" aria-selected={status === f}
            onClick={() => { setStatus(f); setOffset(0); }}
            className={status === f ? "btn-primary" : "btn-secondary"}>{f ?? "all"}</button>
        ))}
      </div>
      <div className="card overflow-x-auto p-0">
        <QueryView q={q} isEmpty={(d) => d.items.length === 0} empty={`No ${status ?? ""} incidents.`}>
          {(page) => (
            <>
              <table className="min-w-full divide-y divide-slate-200">
                <thead><tr>{["#", "Status", "Severity", "Suspected", "Host", "Opened", "Duration", "Anomalies", "Zabbix"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {page.items.map((i) => (
                    <tr key={i.id}>
                      <td className="td"><Link className="text-indigo-700 hover:underline" to={`/incidents/${i.id}`}>#{i.id}</Link></td>
                      <td className="td"><StatusBadge status={i.status} /></td>
                      <td className="td"><SeverityBadge severity={i.severity} /></td>
                      <td className="td"><Suspected category={i.category} score={i.max_score} /></td>
                      <td className="td">{i.host_name}</td>
                      <td className="td">{fmtTime(i.opened_at)}</td>
                      <td className="td">{fmtDuration(i.opened_at, i.resolved_at ?? i.last_seen_at)}</td>
                      <td className="td">{i.anomaly_count}</td>
                      <td className="td">{i.linked_events ? `${i.linked_events} linked` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-between px-4 py-2 text-sm text-slate-600">
                <span>{page.total} incident(s)</span>
                <span className="flex gap-1">
                  <button className="btn-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
                  <button className="btn-secondary" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>Next</button>
                </span>
              </div>
            </>
          )}
        </QueryView>
      </div>
    </div>
  );
}

function Actions({ id, status }: { id: number; status: IncidentStatus }) {
  const [note, setNote] = useState("");
  const ack = useIncidentAction("acknowledge");
  const res = useIncidentAction("resolve");
  if (status === "resolved") return null;
  const busy = ack.isPending || res.isPending;
  return (
    <div className="card space-y-2">
      <label htmlFor="note" className="text-sm font-medium text-slate-700">Analyst note (stored locally, not sent to Zabbix)</label>
      <textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000}
        className="w-full rounded-md border border-slate-300 p-2 text-sm" placeholder="e.g. confirmed scan from known pentest host" />
      <div className="flex gap-2">
        {status === "open" && (
          <button className="btn-primary" disabled={busy} onClick={() => ack.mutate({ id, note })}>Acknowledge</button>
        )}
        <button className="btn-secondary" disabled={busy} onClick={() => res.mutate({ id, note })}>Resolve</button>
      </div>
      {(ack.error || res.error) && <ErrorState error={ack.error ?? res.error} />}
    </div>
  );
}

export function IncidentDetailPage() {
  const id = Number(useParams().id);
  const q = useIncident(id);
  const health = useHealth();
  return (
    <QueryView q={q}>
      {(i) => (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold">Incident #{i.id}</h1>
            <StatusBadge status={i.status} /><SeverityBadge severity={i.severity} />
          </div>
          <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
            <Suspected category={i.category} score={i.max_score} /> on <Link className="underline" to={`/hosts/${i.host_id}`}>{i.host_name}</Link>.
            {" "}This is a model-based detection grouped from {i.anomaly_count} anomalous windows; it is not a confirmed attack.
          </p>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="card space-y-1 text-sm">
              <p><span className="text-slate-500">Opened:</span> {fmtTime(i.opened_at)}</p>
              <p><span className="text-slate-500">Last anomaly:</span> {fmtTime(i.last_seen_at)}</p>
              <p><span className="text-slate-500">Duration:</span> {fmtDuration(i.opened_at, i.resolved_at ?? i.last_seen_at)}</p>
              {i.acknowledged_at && <p><span className="text-slate-500">Acknowledged:</span> {fmtTime(i.acknowledged_at)}</p>}
              {i.resolved_at && <p><span className="text-slate-500">Resolved:</span> {fmtTime(i.resolved_at)} ({i.resolution})</p>}
              <p><span className="text-slate-500">Score:</span> max {i.max_score.toFixed(3)} · mean {i.mean_score.toFixed(3)}</p>
              {i.note && <p><span className="text-slate-500">Note:</span> {i.note}</p>}
            </div>
            <div className="card">
              <p className="mb-2 text-sm font-medium text-slate-700">Suspected category per anomalous window</p>
              <CategoryBars counts={i.category_counts} />
              <p className="mt-2 text-xs text-slate-500">The category is a hint: the model confuses similar classes (e.g. DoS vs DDoS).</p>
            </div>
            <Actions id={i.id} status={i.status} />
          </div>
          <section className="card">
            <h2 className="mb-2 text-sm font-semibold text-slate-700">Score timeline (±2 min)</h2>
            <ScoreChart points={i.timeline} threshold={health.data?.model?.threshold} />
          </section>
          <section className="card p-0">
            <h2 className="px-4 py-3 text-sm font-semibold text-slate-700">Correlated Zabbix problems ({i.events.length})</h2>
            {i.events.length === 0 ? <p className="px-4 pb-4 text-sm text-slate-500">No Zabbix problem overlaps this incident.</p> : (
              <ul className="divide-y divide-slate-100">
                {i.events.map((e) => (
                  <li key={e.id} className="flex flex-wrap gap-3 px-4 py-2 text-sm">
                    <span className="font-medium">{e.name}</span>
                    <span className="text-slate-500">{ZABBIX_SEVERITY[e.severity] ?? e.severity}</span>
                    <span className="ml-auto text-xs text-slate-500">{fmtTime(e.clock)} → {e.recovered_at ? fmtTime(e.recovered_at) : "still open"}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card overflow-x-auto p-0">
            <h2 className="px-4 py-3 text-sm font-semibold text-slate-700">Anomalous windows ({i.anomalies.length})</h2>
            <table className="min-w-full divide-y divide-slate-200">
              <thead><tr>{["Time", "Score", "Suspected category", "Top class probabilities"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-slate-100">
                {i.anomalies.slice(0, 100).map((a) => (
                  <tr key={a.window_id}>
                    <td className="td">{fmtTime(a.ts)}</td>
                    <td className="td">{a.p_attack.toFixed(3)}</td>
                    <td className="td">{a.category}</td>
                    <td className="td text-xs text-slate-500">
                      {Object.entries(a.category_proba).sort((x, y) => y[1] - x[1]).slice(0, 3).map(([k, v]) => `${k} ${(v * 100).toFixed(0)}%`).join(" · ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </QueryView>
  );
}
