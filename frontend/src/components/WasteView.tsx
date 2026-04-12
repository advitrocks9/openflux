import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useWaste, useReplay } from "../hooks/useWaste";
import type { EfficiencyReport, CategoryBreakdown, ToolStep } from "../types";
import { formatDuration, truncate } from "../lib/format";

function fmt(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ── Summary cards ──────────────────────────────────────────────────────

function SummaryCards({ r }: { r: EfficiencyReport }) {
  return (
    <div className="grid grid-cols-4 gap-4">
      <Card label="Sessions" value={r.total_sessions.toLocaleString()} accent="text-accent" />
      <Card label="Tool Calls" value={r.total_tool_calls.toLocaleString()} accent="text-chart-indigo" />
      <Card label="Est. Cost" value={fmt(r.total_cost)} accent="text-chart-amber" />
      <Card label="Redundancy" value={`${r.redundancy_pct.toFixed(1)}%`} sub={`${r.total_redundant_calls} calls`} accent="text-warning" />
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

// ── Bash breakdown bar chart ──────────────────────────────────────────

const BAR_COLORS = [
  "bg-chart-indigo", "bg-chart-indigo-light", "bg-chart-emerald", "bg-chart-amber",
  "bg-accent", "bg-success", "bg-warning", "bg-error", "bg-neutral",
];

function BashBreakdown({ items }: { items: CategoryBreakdown[] }) {
  if (!items.length) return null;
  const max = items[0]?.calls || 1;

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary mb-4">
        What Bash Is Used For
      </div>
      <div className="space-y-2">
        {items.slice(0, 12).map((cat, i) => (
          <div key={cat.name} className="flex items-center gap-3 text-xs">
            <span className="w-44 shrink-0 text-secondary truncate" title={cat.name}>{cat.name}</span>
            <div className="flex-1 h-5 bg-sunken rounded-md overflow-hidden">
              <div
                className={`h-full rounded-md ${BAR_COLORS[i % BAR_COLORS.length]} transition-all duration-500`}
                style={{ width: `${(cat.calls / max) * 100}%` }}
              />
            </div>
            <span className="w-14 text-right font-mono text-primary tabular-nums">{cat.calls.toLocaleString()}</span>
            <span className="w-14 text-right font-mono text-tertiary tabular-nums">{cat.pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Overhead + Redundancy cards ───────────────────────────────────────

function InsightCards({ r }: { r: EfficiencyReport }) {
  return (
    <div className="grid grid-cols-2 gap-4">
      {/* Overhead */}
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-2 h-2 rounded-full bg-neutral" />
          <span className="text-xs font-semibold text-primary">Agent Overhead</span>
          <span className="ml-auto font-mono text-sm text-primary">{r.overhead_pct.toFixed(1)}%</span>
        </div>
        <div className="text-xs text-secondary">
          {r.overhead_calls.toLocaleString()} tool calls are orchestration (TaskCreate, ToolSearch, SendMessage) — not doing actual work.
        </div>
        {/* Mini breakdown of overhead categories */}
        <div className="mt-3 space-y-1">
          {r.categories
            .filter((c) => c.name.startsWith("Overhead"))
            .slice(0, 5)
            .map((c) => (
              <div key={c.name} className="flex justify-between text-xs text-tertiary">
                <span>{c.name.replace("Overhead (", "").replace(")", "")}</span>
                <span className="font-mono">{c.calls}</span>
              </div>
            ))}
        </div>
      </div>

      {/* Redundancy */}
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-2 h-2 rounded-full bg-warning" />
          <span className="text-xs font-semibold text-primary">Redundant Calls</span>
          <span className="ml-auto font-mono text-sm text-primary">{r.total_redundant_calls}</span>
        </div>
        <div className="text-xs text-secondary mb-3">
          Same command repeated within a session without changes between.
        </div>
        <div className="space-y-1.5">
          {r.redundant_patterns.slice(0, 6).map((p) => (
            <div key={p.pattern} className="flex justify-between text-xs">
              <span className="text-secondary truncate mr-2">{p.pattern}</span>
              <span className="font-mono text-warning shrink-0">{p.redundant_calls} / {p.total_calls}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Replay panel ──────────────────────────────────────────────────────

function ToolStepRow({ step }: { step: ToolStep }) {
  return (
    <div className={`flex items-center gap-3 py-1 px-2 rounded text-xs font-mono ${step.error ? "bg-error/5" : ""}`}>
      <span className="w-6 text-right text-tertiary tabular-nums">{step.index}</span>
      <span className={`w-28 shrink-0 font-medium ${step.error ? "text-error" : "text-primary"}`}>{step.name}</span>
      <span className="flex-1 truncate text-tertiary" title={step.target}>{step.target}</span>
      <span className={`w-4 text-center ${step.error ? "text-error" : "text-success"}`}>{step.error ? "✗" : "✓"}</span>
      <span className="w-28 text-right truncate text-tertiary" title={step.output_summary}>{step.output_summary}</span>
    </div>
  );
}

function ReplayPanel({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const { replay, loading } = useReplay(traceId);

  if (loading) {
    return (
      <div className="h-full flex flex-col">
        <div className="px-5 py-4 border-b border-border flex justify-between items-center">
          <div className="h-5 w-48 bg-sunken animate-pulse rounded" />
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-surface-hover text-tertiary cursor-pointer">✕</button>
        </div>
        <div className="flex-1 p-5 space-y-2">
          {Array.from({ length: 15 }).map((_, i) => (
            <div key={i} className="h-6 bg-sunken animate-pulse rounded" style={{ animationDelay: `${i * 30}ms`, width: `${70 + Math.random() * 30}%` }} />
          ))}
        </div>
      </div>
    );
  }

  if (!replay) {
    return (
      <div className="h-full flex flex-col">
        <div className="px-5 py-4 border-b border-border flex justify-between items-center">
          <span className="text-sm text-secondary">Trace not found</span>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-surface-hover text-tertiary cursor-pointer">✕</button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-5 py-4 border-b border-border shrink-0">
        <div className="flex justify-between items-start">
          <div className="min-w-0">
            <div className="font-mono text-xs text-tertiary">{replay.trace_id}</div>
            <div className="text-sm font-medium text-primary mt-1 truncate">{truncate(replay.task || "—", 60)}</div>
            <div className="flex gap-3 mt-2 text-xs text-secondary">
              <span className={replay.status === "error" ? "text-error" : "text-success"}>{replay.status}</span>
              <span>{replay.turn_count} turns</span>
              <span className="font-mono">{fmt(replay.total_cost)}</span>
              <span>{formatDuration(replay.duration_ms)}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-surface-hover text-tertiary cursor-pointer shrink-0">✕</button>
        </div>
      </div>

      {/* Breakdown + redundancy summary */}
      {(replay.tool_breakdown.length > 0 || replay.redundant_in_session.length > 0) && (
        <div className="px-5 py-3 border-b border-border shrink-0 space-y-2">
          {replay.tool_breakdown.slice(0, 5).map((b) => (
            <div key={b.name} className="flex justify-between text-xs">
              <span className="text-secondary">{b.name}</span>
              <span className="font-mono text-primary">{b.calls} <span className="text-tertiary">({b.pct.toFixed(0)}%)</span></span>
            </div>
          ))}
          {replay.redundant_in_session.length > 0 && (
            <div className="pt-1.5 border-t border-border">
              {replay.redundant_in_session.slice(0, 3).map((p) => (
                <div key={p.pattern} className="flex justify-between text-xs">
                  <span className="text-warning">{p.pattern}</span>
                  <span className="font-mono text-warning">{p.redundant_calls} redundant</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tool sequence */}
      <div className="flex-1 overflow-auto px-3 py-3 space-y-0.5">
        {replay.tools.map((step) => (
          <ToolStepRow key={step.index} step={step} />
        ))}
        {replay.tools.length === 0 && (
          <div className="text-xs text-tertiary text-center py-8">No tool calls recorded</div>
        )}
      </div>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="pb-6 px-5 pt-5 space-y-4">
      <div className="grid grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-surface animate-pulse rounded-xl border border-border" style={{ animationDelay: `${i * 75}ms` }} />
        ))}
      </div>
      <div className="h-64 bg-surface animate-pulse rounded-xl border border-border" />
      <div className="grid grid-cols-2 gap-4">
        {[0, 1].map((i) => (
          <div key={i} className="h-48 bg-surface animate-pulse rounded-xl border border-border" />
        ))}
      </div>
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────

export function WasteView() {
  const { report, loading } = useWaste(30);
  const [replayId, setReplayId] = useState<string | null>(null);

  if (loading) return <Skeleton />;

  if (!report || report.total_sessions === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-secondary gap-3">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-tertiary">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <div className="text-sm">No data for the last 30 days</div>
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      <div className={`flex-1 min-w-0 overflow-auto pb-6 transition-all duration-200`}>
        <div className="px-5 pt-5 space-y-4">
          <SummaryCards r={report} />
          <BashBreakdown items={report.bash_breakdown} />
          <InsightCards r={report} />
        </div>
      </div>

      <AnimatePresence>
        {replayId && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 560, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="flex-shrink-0 border-l border-border overflow-hidden"
          >
            <div className="w-[560px] h-full">
              <ReplayPanel traceId={replayId} onClose={() => setReplayId(null)} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
