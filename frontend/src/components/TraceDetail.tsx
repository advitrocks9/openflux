import { useState } from "react";
import type { Trace, ToolRecord, SourceRecord, ContextRecord } from "../types";
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

// ---------------------------------------------------------------------------
// Inline SVG icons (Lucide-style, no deps)
// ---------------------------------------------------------------------------

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

function CloseIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Status badge helper
// ---------------------------------------------------------------------------

function statusColor(status: string): { dot: string; text: string } {
  switch (status.toLowerCase()) {
    case "success":
    case "completed":
      return { dot: "bg-success", text: "text-success" };
    case "error":
    case "failed":
      return { dot: "bg-error", text: "text-error" };
    case "running":
    case "in_progress":
      return { dot: "bg-warning", text: "text-warning" };
    default:
      return { dot: "bg-neutral", text: "text-neutral" };
  }
}

function StatusBadge({ status }: { status: string }) {
  const { dot, text } = statusColor(status);
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${text}`}>
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${dot}`} />
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Collapsible section
// ---------------------------------------------------------------------------

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
        className="flex items-center gap-2 w-full cursor-pointer py-1.5 text-xs font-medium uppercase tracking-wider text-secondary hover:text-primary transition-colors"
      >
        <ChevronIcon open={open} />
        <span>{title}</span>
        {indicator === "warning" && (
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-warning" />
        )}
        {count !== undefined && (
          <span className="ml-auto tabular-nums text-tertiary">{count}</span>
        )}
      </button>
      {open && <div className="mt-1">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Expandable tool row
// ---------------------------------------------------------------------------

function ToolRow({ tool }: { tool: ToolRecord }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-border rounded-md">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center w-full gap-2 px-2.5 py-1.5 text-xs cursor-pointer hover:bg-surface transition-colors"
      >
        <ChevronIcon open={expanded} />
        <span className="font-medium text-primary">{tool.tool_name}</span>
        {tool.error && (
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-error shrink-0" />
        )}
        <span className="ml-auto font-mono text-tertiary">
          {formatDuration(tool.duration_ms)}
        </span>
      </button>
      {expanded && (
        <div className="px-2.5 pb-2.5 space-y-2">
          {tool.tool_input && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-tertiary mb-0.5">
                Input
              </div>
              <pre className="bg-sunken rounded p-2 text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto text-primary">
                {tool.tool_input}
              </pre>
            </div>
          )}
          {tool.tool_output && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-tertiary mb-0.5">
                Output
              </div>
              <pre className="bg-sunken rounded p-2 text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto text-primary">
                {tool.tool_output}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Expandable source row
// ---------------------------------------------------------------------------

function SourceRow({ source }: { source: SourceRecord }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-border rounded-md">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center w-full gap-2 px-2.5 py-1.5 text-xs cursor-pointer hover:bg-surface transition-colors"
      >
        <ChevronIcon open={expanded} />
        <span className="font-mono text-primary truncate">{source.path}</span>
        <span className="ml-auto flex items-center gap-2 shrink-0">
          <span className="bg-accent-subtle text-accent px-1.5 py-0.5 rounded text-[10px]">
            {source.source_type}
          </span>
          <span className="font-mono text-tertiary">
            {formatBytes(source.byte_size)}
          </span>
        </span>
      </button>
      {expanded && source.content && (
        <div className="px-2.5 pb-2.5">
          <pre className="bg-sunken rounded p-2 text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto text-primary">
            {source.content}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Expandable context row
// ---------------------------------------------------------------------------

function ContextRow({ record }: { record: ContextRecord }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-border rounded-md">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center w-full gap-2 px-2.5 py-1.5 text-xs cursor-pointer hover:bg-surface transition-colors"
      >
        <ChevronIcon open={expanded} />
        <span className="bg-accent-subtle text-accent px-1.5 py-0.5 rounded text-[10px]">
          {record.context_type}
        </span>
        <span className="text-primary truncate">{record.source}</span>
      </button>
      {expanded && record.content && (
        <div className="px-2.5 pb-2.5">
          <pre className="bg-sunken rounded p-2 text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto text-primary">
            {record.content}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton placeholder for loading state
// ---------------------------------------------------------------------------

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded bg-surface ${className}`}
      aria-hidden
    />
  );
}

function LoadingSkeleton() {
  return (
    <div className="p-4 space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-20" />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {Array.from({ length: 10 }).map((_, i) => (
          <Skeleton key={i} className="h-3" />
        ))}
      </div>
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Metadata grid row helper
// ---------------------------------------------------------------------------

function MetaRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <span className="text-tertiary">{label}</span>
      <span className="text-primary">{children}</span>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TraceDetail({ trace, loading, onClose }: TraceDetailProps) {
  if (!trace && !loading) return null;

  const cost =
    trace?.token_usage
      ? estimateCost(
          trace.token_usage.input_tokens,
          trace.token_usage.output_tokens,
          trace.model,
        )
      : null;

  return (
    <div className="w-[480px] h-full flex flex-col border-l border-border bg-background transition-transform duration-200 ease-out">
      {/* ----- Header ----- */}
      <div className="shrink-0 flex items-center justify-between border-b border-border px-4 py-3">
        <span className="font-mono text-xs text-tertiary">
          {trace ? trace.id : "Loading..."}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="text-tertiary hover:text-primary cursor-pointer transition-colors"
          aria-label="Close detail panel"
        >
          <CloseIcon />
        </button>
      </div>

      {/* ----- Body ----- */}
      <div className="overflow-y-auto flex-1 p-4 space-y-4">
        {loading || !trace ? (
          <LoadingSkeleton />
        ) : (
          <>
            {/* 1. Title + status */}
            <div className="space-y-1">
              <p className="text-sm font-medium text-primary">{trace.task}</p>
              <StatusBadge status={trace.status} />
            </div>

            {/* 2. Metadata grid */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <MetaRow label="Agent">{trace.agent}</MetaRow>
              <MetaRow label="Model">
                <span className="font-mono">{trace.model}</span>
              </MetaRow>
              <MetaRow label="Duration">
                {formatDuration(trace.duration_ms)}
              </MetaRow>
              {trace.token_usage && (
                <MetaRow label="Tokens">
                  {formatTokens(trace.token_usage.input_tokens)} in /{" "}
                  {formatTokens(trace.token_usage.output_tokens)} out
                </MetaRow>
              )}
              {cost !== null && (
                <MetaRow label="Est. cost">${cost.toFixed(4)}</MetaRow>
              )}
              <MetaRow label="Session">
                <span className="font-mono">
                  {truncate(trace.session_id, 16)}
                </span>
              </MetaRow>
              {trace.scope && <MetaRow label="Scope">{trace.scope}</MetaRow>}
              <MetaRow label="Turns">{trace.turn_count}</MetaRow>
              <MetaRow label="Timestamp">
                {formatAbsoluteTime(trace.timestamp)}
              </MetaRow>
            </div>

            {/* 3. Tags */}
            {trace.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {trace.tags.map((tag) => (
                  <span
                    key={tag}
                    className="bg-accent-subtle text-accent text-xs px-1.5 py-0.5 rounded"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {/* 4. Decision */}
            {trace.decision && (
              <Section title="Decision">
                <div className="text-sm text-primary whitespace-pre-wrap bg-sunken rounded-md p-3">
                  {trace.decision}
                </div>
              </Section>
            )}

            {/* 5. Correction */}
            {trace.correction && (
              <Section title="Correction" indicator="warning">
                <div className="text-sm text-primary whitespace-pre-wrap bg-sunken rounded-md p-3">
                  {trace.correction}
                </div>
              </Section>
            )}

            {/* 6. Tools */}
            {trace.tools_used.length > 0 && (
              <Section title="Tools" count={trace.tools_used.length}>
                <div className="space-y-1.5">
                  {trace.tools_used.map((tool, i) => (
                    <ToolRow key={`${tool.tool_name}-${i}`} tool={tool} />
                  ))}
                </div>
              </Section>
            )}

            {/* 7. Searches */}
            {trace.searches.length > 0 && (
              <Section title="Searches" count={trace.searches.length}>
                <div className="space-y-1.5">
                  {trace.searches.map((s, i) => (
                    <div
                      key={`${s.query}-${i}`}
                      className="flex items-center gap-2 text-xs border border-border rounded-md px-2.5 py-1.5"
                    >
                      <span className="text-primary truncate flex-1">
                        {s.query}
                      </span>
                      <span className="bg-accent-subtle text-accent px-1.5 py-0.5 rounded text-[10px] shrink-0">
                        {s.engine}
                      </span>
                      <span className="font-mono text-tertiary shrink-0">
                        {s.results_count}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* 8. Sources */}
            {trace.sources_read.length > 0 && (
              <Section title="Sources" count={trace.sources_read.length}>
                <div className="space-y-1.5">
                  {trace.sources_read.map((src, i) => (
                    <SourceRow key={`${src.path}-${i}`} source={src} />
                  ))}
                </div>
              </Section>
            )}

            {/* 9. Context */}
            {trace.context.length > 0 && (
              <Section title="Context" count={trace.context.length}>
                <div className="space-y-1.5">
                  {trace.context.map((ctx, i) => (
                    <ContextRow
                      key={`${ctx.source}-${i}`}
                      record={ctx}
                    />
                  ))}
                </div>
              </Section>
            )}

            {/* 10. Files Modified */}
            {trace.files_modified.length > 0 && (
              <Section title="Files Modified" count={trace.files_modified.length}>
                <div className="space-y-0.5">
                  {trace.files_modified.map((f) => (
                    <div
                      key={f}
                      className="font-mono text-xs text-primary truncate"
                    >
                      {f}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* 11. Metadata */}
            {Object.keys(trace.metadata).length > 0 && (
              <Section title="Metadata" defaultOpen={false}>
                <pre className="bg-sunken rounded-md p-3 text-xs font-mono overflow-x-auto text-primary">
                  {JSON.stringify(trace.metadata, null, 2)}
                </pre>
              </Section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
