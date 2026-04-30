import { useState } from "react";
import { useInsights, useInsightsSessions, useAnomalies } from "../hooks/useWaste";
import type { CostOverview, SessionCost, CostAnomaly } from "../types";
import { formatDuration, truncate } from "../lib/format";

function fmt(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(0)}%`;
}

// ── Summary cards ──────────────────────────────────────────────────────

function SummaryCards({ o }: { o: CostOverview }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <Card label="Total Spend" value={fmt(o.total_cost)} accent="text-chart-amber" />
      <Card label="Cache Hit Rate" value={pct(o.cache_hit_ratio)} sub={`${fmt(o.cache_savings)} saved`} accent="text-success" />
      <Card label="Burn Rate" value={`${fmt(o.daily_burn_rate)}/day`} sub={`${fmt(o.projected_monthly)}/mo projected`} accent="text-accent" />
      <Card label="Sessions" value={o.total_sessions.toLocaleString()} accent="text-chart-indigo" />
    </div>
  );
}

function Card({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent: string }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4 hover:border-border-strong transition-colors">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary">{label}</div>
      <div className={`text-2xl font-semibold font-mono tabular-nums mt-1.5 ${accent}`}>{value}</div>
      {sub && <div className="text-xs text-secondary mt-1">{sub}</div>}
    </div>
  );
}

// ── Model breakdown ──────────────────────────────────────────────────

const BAR_COLORS = [
  "bg-chart-indigo", "bg-chart-indigo-light", "bg-chart-emerald", "bg-chart-amber",
  "bg-accent", "bg-success", "bg-warning", "bg-error", "bg-neutral",
];

function ModelBreakdown({ o }: { o: CostOverview }) {
  if (!o.by_model.length) return null;
  const max = o.by_model[0]?.cost || 1;

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary mb-4">
        Cost by Model
      </div>
      <div className="space-y-2">
        {o.by_model.map((m, i) => (
          <div key={m.model} className="flex items-center gap-3 text-xs">
            <span className="w-44 shrink-0 text-secondary truncate" title={m.model}>{m.model}</span>
            <div className="flex-1 h-5 bg-sunken rounded-md overflow-hidden">
              <div
                className={`h-full rounded-md ${BAR_COLORS[i % BAR_COLORS.length]} transition-all duration-500`}
                style={{ width: `${(m.cost / max) * 100}%` }}
              />
            </div>
            <span className="w-16 text-right font-mono text-primary tabular-nums">{fmt(m.cost)}</span>
            <span className="w-14 text-right font-mono text-tertiary tabular-nums">
              {m.cache_read_tokens ? pct(m.cache_hit_ratio) : "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Daily cost chart ─────────────────────────────────────────────────

function DailyChart({ o }: { o: CostOverview }) {
  if (!o.by_day.length) return null;
  const max = Math.max(...o.by_day.map((d) => d.cost));
  const dayCount = o.by_day.length;
  // Tighter gap for many bars so they don't become invisible
  const gapClass = dayCount > 30 ? "gap-px" : dayCount > 14 ? "gap-0.5" : "gap-1.5";
  // Show labels only when there's room
  const showLabels = dayCount <= 31;

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary mb-4">
        Daily Spend
      </div>
      <div className={`flex items-end ${gapClass}`} style={{ height: 140 }}>
        {o.by_day.map((d) => {
          const h = max > 0 ? (d.cost / max) * 100 : 0;
          const cacheColor = d.cache_hit_ratio > 0.5 ? "bg-success" : d.cache_hit_ratio > 0 ? "bg-chart-amber" : "bg-chart-indigo";
          return (
            <div key={d.date} className="flex-1 flex flex-col items-center gap-1" title={`${d.date}: ${fmt(d.cost)} (cache: ${pct(d.cache_hit_ratio)})`}>
              <div className="w-full flex flex-col justify-end" style={{ height: 120 }}>
                <div className={`w-full rounded-t-sm ${cacheColor} transition-all duration-500`} style={{ height: `${h}%`, minHeight: d.cost > 0 ? 2 : 0 }} />
              </div>
              {showLabels && (
                <span className="text-[9px] text-tertiary tabular-nums">{d.date.slice(5)}</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-4 mt-3 text-[10px] text-tertiary">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-success" /> Cache &gt;50%</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-chart-amber" /> Cache &lt;50%</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-chart-indigo" /> No cache</span>
      </div>
    </div>
  );
}

// ── Sessions table ───────────────────────────────────────────────────

function SessionsTable({ sessions }: { sessions: SessionCost[] }) {
  if (!sessions.length) return null;

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary mb-4">
        Most Expensive Sessions
      </div>
      <div className="space-y-1">
        {sessions.slice(0, 10).map((s) => (
          <div key={s.trace_id} className="flex items-center gap-3 py-1.5 px-2 rounded hover:bg-surface-hover text-xs">
            <span className={`w-4 shrink-0 text-center ${s.status === "error" ? "text-error" : "text-success"}`}>
              {s.status === "error" ? "✗" : "✓"}
            </span>
            <span className="w-16 shrink-0 font-mono text-chart-amber tabular-nums text-right">{fmt(s.cost)}</span>
            <span className="w-14 shrink-0 font-mono tabular-nums text-right">
              {s.cache_read_tokens ? (
                <span className={s.cache_hit_ratio > 0.5 ? "text-success" : "text-warning"}>
                  {pct(s.cache_hit_ratio)}
                </span>
              ) : (
                <span className="text-tertiary">—</span>
              )}
            </span>
            <span className="w-16 shrink-0 text-right text-tertiary">{s.tool_count} tools</span>
            <span className="w-14 shrink-0 text-right text-tertiary">{formatDuration(s.duration_ms)}</span>
            <span className="flex-1 min-w-0 truncate text-secondary" title={s.task}>{truncate(s.task || "—", 50)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Anomalies panel ──────────────────────────────────────────────────

const ANOMALY_COLORS: Record<string, string> = {
  cost_spike: "text-chart-amber",
  cache_miss: "text-warning",
  error_storm: "text-error",
  loop: "text-error",
};

const ANOMALY_LABELS: Record<string, string> = {
  cost_spike: "Cost Spike",
  cache_miss: "Cache Miss",
  error_storm: "Error Storm",
  loop: "Agent Loop",
};

function AnomaliesPanel({ anomalies }: { anomalies: CostAnomaly[] }) {
  if (!anomalies.length) {
    return (
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary mb-3">
          Anomalies
        </div>
        <div className="text-xs text-success">No anomalies detected</div>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary">
          Anomalies
        </div>
        <span className="text-xs font-mono text-warning">{anomalies.length} found</span>
      </div>
      <div className="space-y-2">
        {anomalies.slice(0, 8).map((a, i) => (
          <div key={`${a.trace_id}-${i}`} className="flex items-start gap-2 py-1.5 text-xs">
            <span className={`shrink-0 mt-0.5 ${a.severity === "critical" ? "text-error" : "text-warning"}`}>
              {a.severity === "critical" ? "✗" : "⚠"}
            </span>
            <div className="min-w-0">
              <span className={`font-medium ${ANOMALY_COLORS[a.type] || "text-primary"}`}>
                {ANOMALY_LABELS[a.type] || a.type}
              </span>
              <span className="text-tertiary ml-2 font-mono">{a.trace_id}</span>
              <div className="text-secondary mt-0.5">{a.description}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="flex-1 min-h-0 overflow-auto pb-6 px-5 pt-5 space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-surface animate-pulse rounded-xl border border-border" style={{ animationDelay: `${i * 75}ms` }} />
        ))}
      </div>
      <div className="h-48 bg-surface animate-pulse rounded-xl border border-border" />
      <div className="grid grid-cols-2 gap-4">
        {[0, 1].map((i) => (
          <div key={i} className="h-48 bg-surface animate-pulse rounded-xl border border-border" />
        ))}
      </div>
    </div>
  );
}

// ── Time selector ────────────────────────────────────────────────────

const TIME_OPTIONS = [
  { label: "24h", value: 1 },
  { label: "7d", value: 7 },
  { label: "14d", value: 14 },
  { label: "30d", value: 30 },
  { label: "90d", value: 90 },
];

function TimeSelector({ days, onChange }: { days: number; onChange: (d: number) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-lg bg-surface border border-border p-0.5">
      {TIME_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-3 py-1 text-xs font-medium rounded-md cursor-pointer transition-all duration-200 ${
            days === opt.value
              ? "bg-accent-subtle text-accent shadow-sm"
              : "text-secondary hover:text-primary"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────

export function WasteView() {
  const [days, setDays] = useState(7);
  const { overview, loading } = useInsights(days);
  const { sessions } = useInsightsSessions(days);
  const { anomalies } = useAnomalies(days);

  if (loading) return <Skeleton />;

  if (!overview || overview.total_sessions === 0) {
    return (
      <div className="flex-1 min-h-0 overflow-auto flex flex-col items-center justify-center text-secondary gap-3">
        <div className="mb-2">
          <TimeSelector days={days} onChange={setDays} />
        </div>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-tertiary">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <div className="text-sm">No data for the last {days} days</div>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 overflow-auto">
      <div className="px-5 pt-5 pb-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-primary">Cost Intelligence</h2>
          <TimeSelector days={days} onChange={setDays} />
        </div>
        <SummaryCards o={overview} />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ModelBreakdown o={overview} />
          <DailyChart o={overview} />
        </div>
        <SessionsTable sessions={sessions} />
        <AnomaliesPanel anomalies={anomalies} />
      </div>
    </div>
  );
}
