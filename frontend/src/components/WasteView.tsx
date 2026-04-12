import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useWaste, useReplay } from "../hooks/useWaste";
import type { WasteReport, ToolStep } from "../types";
import { formatDuration, truncate } from "../lib/format";

function fmt(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(part: number, total: number): string {
  if (total <= 0) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

// ── Summary cards ──────────────────────────────────────────────────────

function SummaryCards({ r }: { r: WasteReport }) {
  const waste = r.loop_cost + r.errors.total_cost + r.reloads.total_cost;
  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="bg-surface border border-border rounded-xl p-4">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary">
          Total Spend
        </div>
        <div className="text-2xl font-semibold text-primary font-mono tabular-nums mt-1.5">
          {fmt(r.total_cost)}
        </div>
        <div className="text-xs text-secondary mt-1">{r.total_sessions} sessions</div>
      </div>
      <div className="bg-surface border border-border rounded-xl p-4">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary">
          Productive
        </div>
        <div className="text-2xl font-semibold text-success font-mono tabular-nums mt-1.5">
          {fmt(r.productive_cost)}
        </div>
        <div className="text-xs text-secondary mt-1">{pct(r.productive_cost, r.total_cost)}</div>
      </div>
      <div className="bg-surface border border-border rounded-xl p-4">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary">
          Waste Detected
        </div>
        <div className="text-2xl font-semibold text-error font-mono tabular-nums mt-1.5">
          {fmt(waste)}
        </div>
        <div className="text-xs text-secondary mt-1">{pct(waste, r.total_cost)}</div>
      </div>
    </div>
  );
}

// ── Waste bar ──────────────────────────────────────────────────────────

function WasteBar({ r }: { r: WasteReport }) {
  if (r.total_cost <= 0) return null;

  const prodW = (r.productive_cost / r.total_cost) * 100;
  const loopW = (r.loop_cost / r.total_cost) * 100;
  const errW = (r.errors.total_cost / r.total_cost) * 100;
  const relW = (r.reloads.total_cost / r.total_cost) * 100;

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary mb-3">
        Spend Breakdown
      </div>
      <div className="flex h-4 rounded-full overflow-hidden gap-px">
        {prodW > 0 && (
          <div
            className="bg-success rounded-l-full transition-all duration-500"
            style={{ width: `${prodW}%` }}
            title={`Productive: ${fmt(r.productive_cost)}`}
          />
        )}
        {loopW > 0 && (
          <div
            className="bg-error transition-all duration-500"
            style={{ width: `${loopW}%` }}
            title={`Loops: ${fmt(r.loop_cost)}`}
          />
        )}
        {errW > 0 && (
          <div
            className="bg-warning transition-all duration-500"
            style={{ width: `${errW}%` }}
            title={`Errors: ${fmt(r.errors.total_cost)}`}
          />
        )}
        {relW > 0 && (
          <div
            className="bg-neutral rounded-r-full transition-all duration-500"
            style={{ width: `${relW}%` }}
            title={`Reloads: ${fmt(r.reloads.total_cost)}`}
          />
        )}
      </div>
      <div className="flex gap-5 mt-3">
        <Legend color="bg-success" label="Productive" value={fmt(r.productive_cost)} />
        {r.loop_cost > 0 && <Legend color="bg-error" label="Loops" value={fmt(r.loop_cost)} />}
        {r.errors.total_cost > 0 && <Legend color="bg-warning" label="Errors" value={fmt(r.errors.total_cost)} />}
        {r.reloads.total_cost > 0 && <Legend color="bg-neutral" label="Reloads" value={fmt(r.reloads.total_cost)} />}
      </div>
    </div>
  );
}

function Legend({ color, label, value }: { color: string; label: string; value: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-secondary">
      <span className={`w-2.5 h-2.5 rounded-full ${color}`} />
      {label}
      <span className="font-mono text-primary">{value}</span>
    </span>
  );
}

// ── Waste categories ──────────────────────────────────────────────────

function WasteCategories({ r, onSelectTrace }: { r: WasteReport; onSelectTrace: (id: string) => void }) {
  return (
    <div className="grid grid-cols-3 gap-4">
      {/* Loops */}
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-2 h-2 rounded-full bg-error" />
          <span className="text-xs font-semibold text-primary">Agent Loops</span>
        </div>
        {r.loops.length > 0 ? (
          <>
            <div className="text-xl font-semibold text-primary font-mono">{fmt(r.loop_cost)}</div>
            <div className="text-xs text-secondary mt-1">
              {r.loops.length} session{r.loops.length !== 1 ? "s" : ""} with edit→test cycles that never converged
            </div>
            <div className="mt-3 space-y-1.5">
              {r.loops.slice(0, 3).map((l) => (
                <button
                  key={l.trace_id}
                  onClick={() => onSelectTrace(l.trace_id)}
                  className="w-full text-left px-2.5 py-1.5 rounded-md bg-sunken hover:bg-surface-hover transition-colors text-xs cursor-pointer"
                >
                  <div className="flex justify-between">
                    <span className="font-mono text-tertiary">{l.trace_id.slice(-12)}</span>
                    <span className="font-mono text-error">{fmt(l.cost)}</span>
                  </div>
                  <div className="text-secondary mt-0.5 truncate">{l.task || "—"}</div>
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="text-xs text-tertiary mt-2">No loops detected</div>
        )}
      </div>

      {/* Errors */}
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-2 h-2 rounded-full bg-warning" />
          <span className="text-xs font-semibold text-primary">Error Sessions</span>
        </div>
        {r.errors.total_count > 0 ? (
          <>
            <div className="text-xl font-semibold text-primary font-mono">{fmt(r.errors.total_cost)}</div>
            <div className="text-xs text-secondary mt-1">
              {r.errors.total_count} session{r.errors.total_count !== 1 ? "s" : ""} ended in error
            </div>
            <div className="mt-3 space-y-2 text-xs">
              <div className="flex justify-between text-secondary">
                <span>Fast errors (≤5 turns)</span>
                <span className="font-mono">{r.errors.fast_errors} — {fmt(r.errors.fast_error_cost)}</span>
              </div>
              <div className="flex justify-between text-secondary">
                <span>Slow errors (&gt;20 turns)</span>
                <span className="font-mono">{r.errors.slow_errors} — {fmt(r.errors.slow_error_cost)}</span>
              </div>
            </div>
          </>
        ) : (
          <div className="text-xs text-tertiary mt-2">No errors</div>
        )}
      </div>

      {/* Reloads */}
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-2 h-2 rounded-full bg-neutral" />
          <span className="text-xs font-semibold text-primary">Context Reloads</span>
        </div>
        {r.reloads.count > 0 ? (
          <>
            <div className="text-xl font-semibold text-primary font-mono">{fmt(r.reloads.total_cost)}</div>
            <div className="text-xs text-secondary mt-1">
              {r.reloads.count} session{r.reloads.count !== 1 ? "s" : ""} restarted within 10 min
            </div>
            <div className="mt-3 text-xs text-tertiary">
              Resuming with <code className="px-1 py-0.5 bg-sunken rounded text-secondary font-mono">claude --continue</code> would reuse cached context.
            </div>
          </>
        ) : (
          <div className="text-xs text-tertiary mt-2">No unnecessary reloads</div>
        )}
      </div>
    </div>
  );
}

// ── Replay panel ──────────────────────────────────────────────────────

function ToolStepRow({ step, isLoopStart, loopCycles }: { step: ToolStep; isLoopStart: boolean; loopCycles: number }) {
  return (
    <>
      {isLoopStart && (
        <div className="flex items-center gap-2 py-1.5 px-3 my-1 bg-error/10 rounded-md text-xs text-error font-medium">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          Loop detected: {loopCycles} edit→test cycles
        </div>
      )}
      <div className={`flex items-center gap-3 py-1 px-2 rounded text-xs font-mono ${step.error ? "text-error" : "text-secondary"}`}>
        <span className="w-6 text-right text-tertiary tabular-nums">{step.index}</span>
        <span className={`w-28 shrink-0 font-medium ${step.error ? "text-error" : "text-primary"}`}>{step.name}</span>
        <span className="flex-1 truncate text-tertiary" title={step.target}>{step.target}</span>
        <span className="w-4 text-center">{step.error ? "✗" : "✓"}</span>
        <span className="w-28 text-right truncate text-tertiary" title={step.output_summary}>{step.output_summary}</span>
      </div>
    </>
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
              <span className="text-tertiary">{replay.model}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-surface-hover text-tertiary cursor-pointer shrink-0">✕</button>
        </div>

        {/* Cost split */}
        {replay.loop_start !== null && (
          <div className="flex gap-4 mt-3 text-xs">
            <span className="text-success">Productive: {fmt(replay.productive_cost)} ({pct(replay.productive_cost, replay.total_cost)})</span>
            <span className="text-error">Loop waste: {fmt(replay.loop_cost)} ({pct(replay.loop_cost, replay.total_cost)})</span>
          </div>
        )}
      </div>

      {/* Tool sequence */}
      <div className="flex-1 overflow-auto px-3 py-3 space-y-0.5">
        {replay.tools.map((step) => (
          <ToolStepRow
            key={step.index}
            step={step}
            isLoopStart={replay.loop_start !== null && step.index - 1 === replay.loop_start}
            loopCycles={replay.loop_cycles}
          />
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
    <div className="pb-6">
      <div className="grid grid-cols-3 gap-4 px-5 pt-5">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-28 bg-surface animate-pulse rounded-xl border border-border" style={{ animationDelay: `${i * 75}ms` }} />
        ))}
      </div>
      <div className="px-5 pt-4">
        <div className="h-16 bg-surface animate-pulse rounded-xl border border-border" />
      </div>
      <div className="grid grid-cols-3 gap-4 px-5 pt-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-52 bg-surface animate-pulse rounded-xl border border-border" style={{ animationDelay: `${i * 75}ms` }} />
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
        <div className="text-xs text-tertiary">Run some Claude Code sessions first</div>
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main content */}
      <div className={`flex-1 min-w-0 overflow-auto pb-6 ${replayId ? "" : "w-full"} transition-all duration-200`}>
        <div className="px-5 pt-5 space-y-4">
          <SummaryCards r={report} />
          <WasteBar r={report} />
          <WasteCategories r={report} onSelectTrace={setReplayId} />
        </div>
      </div>

      {/* Replay panel */}
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
