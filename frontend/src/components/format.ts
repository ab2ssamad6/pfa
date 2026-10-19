export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
}

export function fmtClock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtDuration(fromIso: string, toIso: string | null): string {
  const s = Math.max(0, Math.round(((toIso ? new Date(toIso) : new Date()).getTime() - new Date(fromIso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export const pct = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`;

export const score = (x: number | null | undefined) => (x === null || x === undefined ? "—" : x.toFixed(3));

export const ZABBIX_SEVERITY = ["Not classified", "Information", "Warning", "Average", "High", "Disaster"];
