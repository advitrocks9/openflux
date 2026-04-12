import type {
  Trace,
  TracesResponse,
  StatsResponse,
  TimelineResponse,
  TraceStats,
  EfficiencyReport,
  SessionReplay,
} from "./types";

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export function fetchTraces(params: {
  limit?: number;
  offset?: number;
  agent?: string;
  search?: string;
  status?: string;
  sort?: string;
  order?: string;
}): Promise<TracesResponse> {
  const qs = new URLSearchParams();
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  if (params.agent) qs.set("agent", params.agent);
  if (params.search) qs.set("search", params.search);
  if (params.status) qs.set("status", params.status);
  if (params.sort) qs.set("sort", params.sort);
  if (params.order) qs.set("order", params.order);
  return get<TracesResponse>(`/traces?${qs.toString()}`);
}

export function fetchTrace(id: string): Promise<Trace> {
  return get<Trace>(`/traces/${id}`);
}

export function fetchStats(): Promise<StatsResponse> {
  return get<StatsResponse>("/stats");
}

export function fetchTimeline(days = 30): Promise<TimelineResponse> {
  return get<TimelineResponse>(`/stats/timeline?days=${days}`);
}

export function fetchTraceStats(id: string): Promise<TraceStats> {
  return get<TraceStats>(`/traces/${id}/stats`);
}

export function fetchWaste(days = 30, agent?: string): Promise<EfficiencyReport> {
  const qs = new URLSearchParams();
  qs.set("days", String(days));
  if (agent) qs.set("agent", agent);
  return get<EfficiencyReport>(`/waste?${qs.toString()}`);
}

export function fetchReplay(id: string): Promise<SessionReplay> {
  return get<SessionReplay>(`/replay/${id}`);
}
