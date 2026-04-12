import { useState, useEffect } from "react";
import { fetchWaste, fetchReplay } from "../api";
import type { WasteReport, SessionReplay } from "../types";

export function useWaste(days = 30) {
  const [report, setReport] = useState<WasteReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchWaste(days)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch(() => {
        if (!cancelled) setReport(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  return { report, loading };
}

export function useReplay(traceId: string | null) {
  const [replay, setReplay] = useState<SessionReplay | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!traceId) {
      setReplay(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchReplay(traceId)
      .then((data) => {
        if (!cancelled) setReplay(data);
      })
      .catch(() => {
        if (!cancelled) setReplay(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [traceId]);

  return { replay, loading };
}
