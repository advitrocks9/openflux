import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import type { Trace, ToolRecord, SourceRecord, ContextRecord } from "../types";
import { StatusBadge } from "./StatusBadge";
import {
  formatTokens,
  formatDuration,
  formatAbsoluteTime,
  formatBytes,
  truncate,
  estimateCost,
} from "../lib/format";

interface TraceDetailProps {
  trace: Trace | null;
  loading: boolean;
  onClose: () => void;
}

type Tab = "overview" | "tools" | "sources" | "raw";

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 transition-transform duration-150 ${open ? "rotate-90" : ""}`}
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function Section({
  title,
  count,
  children,
  defaultOpen = true,
  indicator,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
  defaultOpen?: boolean;
  indicator?: "warning";
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex items-center gap-2 w-full cursor-pointer py-2 text-[11px] font-semibold uppercase tracking-widest text-tertiary hover:text-secondary transition-colors"
      >
        <ChevronIcon open={open} />
        <span>{title}</span>
        {indicator === "warning" && (
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-warning" />
        )}
        {count !== undefined && (
          <span className="ml-auto tabular-nums text-tertiary/60 font-mono text-[10px]">
            {count}
          </span>
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="pb-2">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ToolRow({ tool }: { tool: ToolRecord }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center w-full gap-2 px-3 py-2 text-xs cursor-pointer hover:bg-surface transition-colors duration-150"
      >
        <ChevronIcon open={expanded} />
        <span className="font-medium text-primary">{tool.tool_name}</span>
        {tool.error && (
          <span className="inline-flex items-center rounded-full bg-error-subtle px-1.5 py-0.5 text-[10px] text-error font-medium">
            error
          </span>
        )}
        <span className="ml-auto font-mono text-[11px] text-tertiary tabular-nums">
          {formatDuration(tool.duration_ms)}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-2 border-t border-border pt-2">
              {tool.tool_input && (
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-tertiary font-semibold mb-1">
                    Input
                  </div>
                  <pre className="bg-sunken rounded-md p-2.5 text-[11px] font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto text-primary leading-relaxed">
                    {tool.tool_input}
                  </pre>
                </div>
              )}
              {tool.tool_output && (
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-tertiary font-semibold mb-1">
                    Output
                  </div>
                  <pre className="bg-sunken rounded-md p-2.5 text-[11px] font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto text-primary leading-relaxed">
                    {tool.tool_output}
                  </pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function SourceRow({ source }: { source: SourceRecord }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center w-full gap-2 px-3 py-2 text-xs cursor-pointer hover:bg-surface transition-colors duration-150"
      >
        <ChevronIcon open={expanded} />
        <span className="font-mono text-primary truncate text-[11px]">
          {source.path}
        </span>
        <span className="ml-auto flex items-center gap-2 shrink-0">
          <span className="bg-accent-subtle text-accent px-1.5 py-0.5 rounded-md text-[10px] font-medium">
            {source.source_type}
          </span>
          <span className="font-mono text-[11px] text-tertiary tabular-nums">
            {formatBytes(source.byte_size)}
          </span>
        </span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && source.content && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 border-t border-border pt-2">
              <pre className="bg-sunken rounded-md p-2.5 text-[11px] font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto text-primary leading-relaxed">
                {source.content}
              </pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ContextRow({ record }: { record: ContextRecord }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center w-full gap-2 px-3 py-2 text-xs cursor-pointer hover:bg-surface transition-colors duration-150"
      >
        <ChevronIcon open={expanded} />
        <span className="bg-accent-subtle text-accent px-1.5 py-0.5 rounded-md text-[10px] font-medium">
          {record.context_type}
        </span>
        <span className="text-primary truncate text-[11px]">{record.source}</span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && record.content && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 border-t border-border pt-2">
              <pre className="bg-sunken rounded-md p-2.5 text-[11px] font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto text-primary leading-relaxed">
                {record.content}
              </pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded-md bg-surface ${className}`} aria-hidden />
  );
}

function LoadingSkeleton() {
  return (
    <div className="p-5 space-y-5">
      <div className="space-y-2">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-3 w-20" />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        {Array.from({ length: 10 }).map((_, i) => (
          <Skeleton key={i} className="h-3" />
        ))}
      </div>
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <span className="text-tertiary text-[11px]">{label}</span>
      <span className="text-primary text-xs">{children}</span>
    </>
  );
}

function TabButton({
  label,
  active,
  count,
  onClick,
}: {
  label: string;
  active: boolean;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative px-3 py-2 text-xs font-medium cursor-pointer transition-colors duration-200 ${
        active ? "text-accent" : "text-tertiary hover:text-secondary"
      }`}
    >
      <span className="flex items-center gap-1.5">
        {label}
        {count !== undefined && count > 0 && (
          <span className="font-mono text-[10px] tabular-nums bg-surface rounded-full px-1.5 py-0.5">
            {count}
          </span>
        )}
      </span>
      {active && (
        <motion.div
          layoutId="detail-tab-indicator"
          className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent rounded-full"
          transition={{ duration: 0.2, ease: "easeOut" }}
        />
      )}
    </button>
  );
}

export function TraceDetail({ trace, loading, onClose }: TraceDetailProps) {
  const [tab, setTab] = useState<Tab>("overview");

  if (!trace && !loading) return null;

  const cost =
    trace?.token_usage
      ? estimateCost(
          trace.token_usage.input_tokens,
          trace.token_usage.output_tokens,
          trace.model,
        )
      : null;

  const toolCount = trace?.tools_used.length ?? 0;
  const sourceCount = trace?.sources_read.length ?? 0;

  return (
    <div className="h-full flex flex-col bg-background">
      <div className="shrink-0 flex items-center justify-between border-b border-border px-5 py-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-[11px] text-tertiary truncate">
            {trace ? trace.id : "Loading\u2026"}
          </span>
          {trace && <StatusBadge status={trace.status} />}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-tertiary hover:text-primary cursor-pointer transition-colors duration-200 p-1 rounded-md hover:bg-surface"
          aria-label="Close detail panel"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <div className="shrink-0 flex items-center border-b border-border px-2">
        <TabButton label="Overview" active={tab === "overview"} onClick={() => setTab("overview")} />
        <TabButton label="Tools" active={tab === "tools"} count={toolCount} onClick={() => setTab("tools")} />
        <TabButton label="Sources" active={tab === "sources"} count={sourceCount} onClick={() => setTab("sources")} />
        <TabButton label="Raw" active={tab === "raw"} onClick={() => setTab("raw")} />
      </div>

      <div className="overflow-y-auto flex-1 p-5">
        {loading || !trace ? (
          <LoadingSkeleton />
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.15 }}
            >
              {tab === "overview" && <OverviewTab trace={trace} cost={cost} />}
              {tab === "tools" && <ToolsTab trace={trace} />}
              {tab === "sources" && <SourcesTab trace={trace} />}
              {tab === "raw" && <RawTab trace={trace} />}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

function OverviewTab({ trace, cost }: { trace: Trace; cost: number | null }) {
  return (
    <div className="space-y-5">
      <p className="text-sm font-medium text-primary leading-snug">{trace.task}</p>

      <div className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-2">
        <MetaRow label="Agent">{trace.agent}</MetaRow>
        <MetaRow label="Model">
          <span className="font-mono text-[11px]">{trace.model}</span>
        </MetaRow>
        <MetaRow label="Duration">{formatDuration(trace.duration_ms)}</MetaRow>
        {trace.token_usage && (
          <MetaRow label="Tokens">
            <span className="font-mono text-[11px] tabular-nums">
              {formatTokens(trace.token_usage.input_tokens)} in / {formatTokens(trace.token_usage.output_tokens)} out
            </span>
          </MetaRow>
        )}
        {cost !== null && (
          <MetaRow label="Est. cost">
            <span className="font-mono text-[11px]">${cost.toFixed(4)}</span>
          </MetaRow>
        )}
        <MetaRow label="Session">
          <span className="font-mono text-[11px]">{truncate(trace.session_id, 16)}</span>
        </MetaRow>
        {trace.scope && <MetaRow label="Scope">{trace.scope}</MetaRow>}
        <MetaRow label="Turns">
          <span className="tabular-nums">{trace.turn_count}</span>
        </MetaRow>
        <MetaRow label="Timestamp">{formatAbsoluteTime(trace.timestamp)}</MetaRow>
      </div>

      {trace.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {trace.tags.map((tag) => (
            <span
              key={tag}
              className="bg-accent-subtle text-accent text-[11px] font-medium px-2 py-0.5 rounded-md"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {trace.decision && (
        <Section title="Decision">
          <div className="text-sm text-primary whitespace-pre-wrap bg-sunken rounded-lg p-3 leading-relaxed">
            {trace.decision}
          </div>
        </Section>
      )}

      {trace.correction && (
        <Section title="Correction" indicator="warning">
          <div className="text-sm text-primary whitespace-pre-wrap bg-sunken rounded-lg p-3 leading-relaxed border-l-2 border-warning">
            {trace.correction}
          </div>
        </Section>
      )}

      {trace.searches.length > 0 && (
        <Section title="Searches" count={trace.searches.length}>
          <div className="space-y-1.5">
            {trace.searches.map((s, i) => (
              <div
                key={`${s.query}-${i}`}
                className="flex items-center gap-2 text-xs border border-border rounded-lg px-3 py-2"
              >
                <span className="text-primary truncate flex-1 text-[11px]">{s.query}</span>
                <span className="bg-accent-subtle text-accent px-1.5 py-0.5 rounded-md text-[10px] font-medium shrink-0">
                  {s.engine}
                </span>
                <span className="font-mono text-[11px] text-tertiary shrink-0 tabular-nums">
                  {s.results_count}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {trace.context.length > 0 && (
        <Section title="Context" count={trace.context.length}>
          <div className="space-y-1.5">
            {trace.context.map((ctx, i) => (
              <ContextRow key={`${ctx.source}-${i}`} record={ctx} />
            ))}
          </div>
        </Section>
      )}

      {trace.files_modified.length > 0 && (
        <Section title="Files Modified" count={trace.files_modified.length}>
          <div className="space-y-1 bg-sunken rounded-lg p-2.5">
            {trace.files_modified.map((f) => (
              <div key={f} className="font-mono text-[11px] text-primary truncate">
                {f}
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function ToolsTab({ trace }: { trace: Trace }) {
  if (trace.tools_used.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-secondary gap-2">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-tertiary">
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
        </svg>
        <span className="text-xs">No tools used in this trace</span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {trace.tools_used.map((tool, i) => (
        <ToolRow key={`${tool.tool_name}-${i}`} tool={tool} />
      ))}
    </div>
  );
}

function SourcesTab({ trace }: { trace: Trace }) {
  if (trace.sources_read.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-secondary gap-2">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-tertiary">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <span className="text-xs">No sources read in this trace</span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {trace.sources_read.map((src, i) => (
        <SourceRow key={`${src.path}-${i}`} source={src} />
      ))}
    </div>
  );
}

function RawTab({ trace }: { trace: Trace }) {
  return (
    <pre className="bg-sunken rounded-lg p-4 text-[11px] font-mono whitespace-pre-wrap overflow-x-auto text-primary leading-relaxed">
      {JSON.stringify(trace, null, 2)}
    </pre>
  );
}
