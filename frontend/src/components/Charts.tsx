import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ComposedChart, Tooltip, XAxis, YAxis,
} from "recharts";
import type { MetricSeries, ScorePoint } from "../api/types";
import { fmtClock } from "./format";

export function ScoreChart({ points, threshold, height = 220 }: { points: ScorePoint[]; threshold?: number; height?: number }) {
  const data = points.map((p) => ({ t: new Date(p.ts).getTime(), score: p.p_attack, anomaly: p.is_anomaly ? p.p_attack : null }));
  return (
    <div style={{ height }} data-testid="score-chart">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time"
                 tickFormatter={(t) => fmtClock(new Date(t).toISOString())} fontSize={11} />
          <YAxis domain={[0, 1]} fontSize={11} width={32} />
          <Tooltip labelFormatter={(t) => fmtClock(new Date(Number(t)).toISOString())}
                   formatter={(v: number, name) => [v?.toFixed(3), name === "score" ? "attack score" : "anomaly"]} />
          {threshold !== undefined && (
            <ReferenceLine y={threshold} stroke="#dc2626" strokeDasharray="4 4"
                           label={{ value: `threshold ${threshold.toFixed(2)}`, fontSize: 10, fill: "#dc2626", position: "insideTopLeft" }} />
          )}
          <Line type="monotone" dataKey="score" stroke="#4f46e5" dot={false} strokeWidth={1.5} isAnimationActive={false} />
          <Scatter dataKey="anomaly" fill="#dc2626" isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MetricChart({ series, height = 160 }: { series: MetricSeries; height?: number }) {
  const data = series.points.map((p) => ({ t: new Date(p.ts).getTime(), v: p.value }));
  const fmt = (v: number) => (series.units === "bps" ? `${(v / 1e6).toFixed(0)}M` : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0));
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time"
                 tickFormatter={(t) => fmtClock(new Date(t).toISOString())} fontSize={11} />
          <YAxis tickFormatter={fmt} fontSize={11} width={44} />
          <Tooltip labelFormatter={(t) => fmtClock(new Date(Number(t)).toISOString())}
                   formatter={(v: number) => [`${fmt(v)} ${series.units}`, series.name]} />
          <Line type="monotone" dataKey="v" stroke="#0891b2" dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CategoryBars({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return (
    <ul className="space-y-1">
      {entries.map(([k, v]) => (
        <li key={k} className="flex items-center gap-2 text-sm">
          <span className="w-24 shrink-0 text-slate-600">{k}</span>
          <span className="h-2 rounded bg-indigo-500" style={{ width: `${(v / total) * 100}%` }} />
          <span className="text-xs text-slate-500">{v}</span>
        </li>
      ))}
    </ul>
  );
}
