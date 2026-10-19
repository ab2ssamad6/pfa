import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "./client";
import type {
  Anomaly, ExternalEvent, Health, HostStatus, Incident, IncidentDetail, IncidentStatus, LiveAccuracy,
  MetricSeries, ModelInfo, Overview, Page, ScorePoint, Host,
} from "./types";

/** Near-real-time: the worker produces a window every ~2 s; the dashboard polls every 3 s. */
export const REFRESH_MS = 3000;
const live = { refetchInterval: REFRESH_MS, refetchIntervalInBackground: false };

export const useHealth = () => useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/api/health"), ...live });
export const useOverview = () =>
  useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/api/overview"), ...live });
export const useHosts = () => useQuery({ queryKey: ["hosts"], queryFn: () => api<HostStatus[]>("/api/hosts"), ...live });
export const useHost = (id: number) =>
  useQuery({ queryKey: ["host", id], queryFn: () => api<Host>(`/api/hosts/${id}`) });
export const useScores = (id: number, minutes: number) =>
  useQuery({ queryKey: ["scores", id, minutes], queryFn: () => api<ScorePoint[]>(`/api/hosts/${id}/scores${qs({ minutes })}`), ...live });
export const useMetrics = (id: number, minutes: number) =>
  useQuery({ queryKey: ["metrics", id, minutes], queryFn: () => api<MetricSeries[]>(`/api/hosts/${id}/metrics${qs({ minutes })}`), ...live });

export const useIncidents = (status?: IncidentStatus, hostId?: number, limit = 50, offset = 0) =>
  useQuery({
    queryKey: ["incidents", status, hostId, limit, offset],
    queryFn: () => api<Page<Incident>>(`/api/incidents${qs({ status, host_id: hostId, limit, offset })}`),
    ...live,
  });
export const useIncident = (id: number) =>
  useQuery({ queryKey: ["incident", id], queryFn: () => api<IncidentDetail>(`/api/incidents/${id}`), ...live });
export const useAnomalies = (hostId?: number, limit = 100) =>
  useQuery({ queryKey: ["anomalies", hostId, limit], queryFn: () => api<Page<Anomaly>>(`/api/anomalies${qs({ host_id: hostId, limit })}`), ...live });
export const useEvents = (activeOnly = false) =>
  useQuery({ queryKey: ["events", activeOnly], queryFn: () => api<ExternalEvent[]>(`/api/events${qs({ active_only: activeOnly ? "true" : undefined })}`), ...live });
export const useModel = () => useQuery({ queryKey: ["model"], queryFn: () => api<ModelInfo>("/api/model") });
export const useLiveAccuracy = (minutes = 15) =>
  useQuery({
    queryKey: ["live-accuracy", minutes],
    queryFn: () => api<LiveAccuracy>(`/api/demo/live-accuracy${qs({ minutes })}`),
    refetchInterval: 10000,
    retry: false,
  });

export function useIncidentAction(action: "acknowledge" | "resolve") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: number; note?: string }) =>
      api<Incident>(`/api/incidents/${id}/${action}`, { method: "POST", body: JSON.stringify({ note: note || null }) }),
    onSuccess: (inc) => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["incident", inc.id] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      qc.invalidateQueries({ queryKey: ["hosts"] });
    },
  });
}
