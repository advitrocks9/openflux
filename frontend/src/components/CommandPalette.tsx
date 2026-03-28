import { useEffect, useCallback } from "react";
import { Command } from "cmdk";
import type { Trace } from "../types";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  traces: Trace[];
  onSelectTrace: (id: string) => void;
  onNavigate: (view: "traces" | "stats") => void;
}

function GridIcon() {
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
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
    </svg>
  );
}

function ChartIcon() {
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
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  );
}

function ExportIcon() {
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
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

const ITEM_CLASS =
  "flex items-center gap-3 px-3 py-2 text-sm text-primary rounded-md cursor-pointer transition-colors duration-150 data-[selected=true]:bg-accent-subtle";

export function CommandPalette({
  open,
  onOpenChange,
  traces,
  onSelectTrace,
  onNavigate,
}: CommandPaletteProps) {
  const close = useCallback(() => onOpenChange(false), [onOpenChange]);

  // Close on escape
  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        close();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, close]);

  if (!open) return null;

  const recentTraces = traces.slice(0, 5);

  return (
    <div className="fixed inset-0 z-50">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={close}
      />

      {/* Dialog */}
      <div className="absolute inset-0 flex items-start justify-center pt-[20vh]">
        <div className="w-[560px] max-h-[400px] bg-background border border-border-strong rounded-xl shadow-2xl overflow-hidden">
          <Command label="Command palette" shouldFilter>
            <Command.Input
              placeholder="Search traces, navigate..."
              className="border-b border-border px-4 py-3 text-sm text-primary placeholder:text-tertiary outline-none bg-transparent w-full"
            />
            <Command.List className="max-h-[320px] overflow-y-auto p-2">
              <Command.Empty className="text-secondary text-sm text-center py-8">
                No results found
              </Command.Empty>

              {recentTraces.length > 0 && (
                <Command.Group
                  heading="Recent Traces"
                  className="[&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-tertiary [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5"
                >
                  {recentTraces.map((trace) => (
                    <Command.Item
                      key={trace.id}
                      value={`${trace.id} ${trace.task}`}
                      onSelect={() => {
                        onSelectTrace(trace.id);
                        close();
                      }}
                      className={ITEM_CLASS}
                    >
                      <span className="font-mono text-xs text-tertiary shrink-0">
                        {trace.id.slice(0, 12)}
                      </span>
                      <span className="truncate">{trace.task || "Untitled"}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}

              <Command.Group
                heading="Navigation"
                className="[&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-tertiary [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5"
              >
                <Command.Item
                  value="Traces"
                  onSelect={() => {
                    onNavigate("traces");
                    close();
                  }}
                  className={ITEM_CLASS}
                >
                  <GridIcon />
                  <span>Traces</span>
                </Command.Item>
                <Command.Item
                  value="Stats"
                  onSelect={() => {
                    onNavigate("stats");
                    close();
                  }}
                  className={ITEM_CLASS}
                >
                  <ChartIcon />
                  <span>Stats</span>
                </Command.Item>
              </Command.Group>

              <Command.Group
                heading="Actions"
                className="[&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-tertiary [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5"
              >
                <Command.Item
                  value="Export as JSON"
                  onSelect={() => {
                    window.open("/api/traces?format=ndjson", "_blank");
                    close();
                  }}
                  className={ITEM_CLASS}
                >
                  <ExportIcon />
                  <span>Export as JSON</span>
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </div>
      </div>
    </div>
  );
}
