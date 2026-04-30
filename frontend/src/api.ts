import type {
  Trace,
  TracesResponse,
  StatsResponse,
  TimelineResponse,
  TraceStats,
  CostOverview,
  SessionCost,
  CostAnomaly,
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

export function fetchInsights(days = 7, agent?: string): Promise<CostOverview> {
  const qs = new URLSearchParams();
  qs.set("days", String(days));
  if (agent) qs.set("agent", agent);
  return get<CostOverview>(`/insights?${qs.toString()}`);
}

export function fetchInsightsSessions(
  days = 7,
  agent?: string,
  limit = 20,
  sort = "cost",
): Promise<{ sessions: SessionCost[] }> {
  const qs = new URLSearchParams();
  qs.set("days", String(days));
  qs.set("limit", String(limit));
  qs.set("sort", sort);
  if (agent) qs.set("agent", agent);
  return get<{ sessions: SessionCost[] }>(`/insights/sessions?${qs.toString()}`);
}

export function fetchInsightsAnomalies(
  days = 7,
  agent?: string,
): Promise<{ anomalies: CostAnomaly[] }> {
  const qs = new URLSearchParams();
  qs.set("days", String(days));
  if (agent) qs.set("agent", agent);
  return get<{ anomalies: CostAnomaly[] }>(`/insights/anomalies?${qs.toString()}`);
}
