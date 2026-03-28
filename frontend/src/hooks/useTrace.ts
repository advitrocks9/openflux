import { useState, useEffect } from "react";
import type { Trace } from "../types";
import { fetchTrace } from "../api";

interface UseTraceResult {
  trace: Trace | null;
  loading: boolean;
  error: string | null;
}

/** Fill in missing arrays/fields that to_dict() omits when empty. */
function normalizeTrace(raw: Partial<Trace>): Trace {
  return {
    id: raw.id ?? "",
    timestamp: raw.timestamp ?? "",
    agent: raw.agent ?? "",
    session_id: raw.session_id ?? "",
    parent_id: raw.parent_id ?? null,
    model: raw.model ?? "",
    task: raw.task ?? "",
    decision: raw.decision ?? "",
    status: raw.status ?? "unknown",
    correction: raw.correction ?? null,
    scope: raw.scope ?? null,
    tags: raw.tags ?? [],
    context: raw.context ?? [],
    searches: raw.searches ?? [],
    sources_read: raw.sources_read ?? [],
    tools_used: raw.tools_used ?? [],
    files_modified: raw.files_modified ?? [],
    turn_count: raw.turn_count ?? 0,
    token_usage: raw.token_usage ?? null,
    duration_ms: raw.duration_ms ?? 0,
    metadata: raw.metadata ?? {},
    schema_version: raw.schema_version ?? "1.0",
  };
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
        if (!cancelled) setTrace(normalizeTrace(res));
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
