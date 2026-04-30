import { useState, useEffect } from "react";
import { fetchInsights, fetchInsightsSessions, fetchInsightsAnomalies } from "../api";
import type { CostOverview, SessionCost, CostAnomaly } from "../types";

export function useInsights(days = 7) {
  const [overview, setOverview] = useState<CostOverview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchInsights(days)
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch(() => {
        if (!cancelled) setOverview(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  return { overview, loading };
}

export function useInsightsSessions(days = 7, sort = "cost") {
  const [sessions, setSessions] = useState<SessionCost[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchInsightsSessions(days, undefined, 20, sort)
      .then((data) => {
        if (!cancelled) setSessions(data.sessions);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days, sort]);

  return { sessions, loading };
}

export function useAnomalies(days = 7) {
  const [anomalies, setAnomalies] = useState<CostAnomaly[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchInsightsAnomalies(days)
      .then((data) => {
        if (!cancelled) setAnomalies(data.anomalies);
      })
      .catch(() => {
        if (!cancelled) setAnomalies([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  return { anomalies, loading };
}
