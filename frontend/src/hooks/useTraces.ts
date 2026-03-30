import { useState, useEffect, useCallback } from "react";
import type { Trace } from "../types";
import { fetchTraces } from "../api";

interface UseTracesParams {
  limit?: number;
  agent?: string;
  search?: string;
  status?: string;
  sort?: string;
  order?: string;
}

interface UseTracesResult {
  traces: Trace[];
  total: number;
  loading: boolean;
  error: string | null;
  page: number;
  setPage: (p: number) => void;
  refetch: () => void;
}

export function useTraces(params: UseTracesParams = {}): UseTracesResult {
  const { limit = 25, agent, search, status, sort, order } = params;

  const [traces, setTraces] = useState<Trace[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchTraces({
        limit,
        offset: (page - 1) * limit,
        agent,
        search,
        status,
        sort,
        order,
      });
      setTraces(
        res.traces.map((t) => ({
          ...t,
          tags: t.tags ?? [],
          context: t.context ?? [],
          searches: t.searches ?? [],
          sources_read: t.sources_read ?? [],
          tools_used: t.tools_used ?? [],
          files_modified: t.files_modified ?? [],
          token_usage: t.token_usage ?? null,
          metadata: t.metadata ?? {},
        })),
      );
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch traces");
    } finally {
      setLoading(false);
    }
  }, [limit, page, agent, search, status, sort, order]);

  useEffect(() => {
    void fetch();
  }, [fetch]);

  useEffect(() => {
    setPage(1);
  }, [agent, search, status, sort, order]);

  return { traces, total, loading, error, page, setPage, refetch: fetch };
}
