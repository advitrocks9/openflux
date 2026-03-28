import { useState, useEffect } from "react";
import type { StatsResponse, TimelineEntry } from "../types";
import { fetchStats, fetchTimeline } from "../api";

interface UseStatsResult {
  stats: StatsResponse | null;
  timeline: TimelineEntry[];
  loading: boolean;
}

export function useStats(): UseStatsResult {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [statsRes, timelineRes] = await Promise.all([
          fetchStats(),
          fetchTimeline(),
        ]);
        if (!cancelled) {
          setStats(statsRes);
          setTimeline(timelineRes.days);
        }
      } catch {
        // Stats are non-critical; silently degrade
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { stats, timeline, loading };
}
