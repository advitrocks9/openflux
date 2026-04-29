import { useEffect, useState } from "react";
import type { Outcome } from "../types";
import { fetchOutcomes } from "../api";

interface UseOutcomesResult {
  outcomes: Outcome[];
  loading: boolean;
  error: string | null;
}

export function useOutcomes(limit = 50): UseOutcomesResult {
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetchOutcomes(limit);
        if (!cancelled) {
          setOutcomes(res.outcomes);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [limit]);

  return { outcomes, loading, error };
}
