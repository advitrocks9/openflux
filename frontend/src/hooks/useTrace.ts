import { useState, useEffect } from "react";
import type { Trace } from "../types";
import { fetchTrace } from "../api";

interface UseTraceResult {
  trace: Trace | null;
  loading: boolean;
  error: string | null;
}

export function useTrace(id: string | null): UseTraceResult {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) {
      setTrace(null);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchTrace(id)
      .then((res) => {
        if (!cancelled) setTrace(res);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "Failed to fetch trace",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  return { trace, loading, error };
}
