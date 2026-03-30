import { useEffect, useCallback } from "react";
import { Command } from "cmdk";
import { motion, AnimatePresence } from "motion/react";
import type { Trace } from "../types";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  traces: Trace[];
  onSelectTrace: (id: string) => void;
  onNavigate: (view: "traces" | "stats") => void;
}

const ITEM_CLASS =
  "flex items-center gap-3 px-3 py-2.5 text-sm text-primary rounded-lg cursor-pointer transition-colors duration-150 data-[selected=true]:bg-accent-subtle data-[selected=true]:text-accent";

const GROUP_HEADING =
  "[&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-tertiary [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2";

export function CommandPalette({
  open,
  onOpenChange,
  traces,
  onSelectTrace,
  onNavigate,
}: CommandPaletteProps) {
  const close = useCallback(() => onOpenChange(false), [onOpenChange]);

  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, close]);

  const recentTraces = traces.slice(0, 5);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={close}
          />

          <div className="absolute inset-0 flex items-start justify-center pt-[18vh]">
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: -8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: -8 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
              className="w-[540px] max-h-[420px] bg-background border border-border-strong rounded-xl shadow-2xl overflow-hidden"
            >
              <Command label="Command palette" shouldFilter>
                <Command.Input
                  placeholder="Search traces, navigate..."
                  className="border-b border-border px-4 py-3.5 text-sm text-primary placeholder:text-tertiary outline-none bg-transparent w-full"
                  autoFocus
                />
                <Command.List className="max-h-[340px] overflow-y-auto p-1.5">
                  <Command.Empty className="text-secondary text-sm text-center py-10">
                    No results found
                  </Command.Empty>

                  {recentTraces.length > 0 && (
                    <Command.Group heading="Recent Traces" className={GROUP_HEADING}>
                      {recentTraces.map((trace) => (
                        <Command.Item
                          key={trace.id}
                          value={`${trace.id} ${trace.task}`}
                          onSelect={() => { onSelectTrace(trace.id); close(); }}
                          className={ITEM_CLASS}
                        >
                          <span className="font-mono text-[11px] text-tertiary shrink-0 tabular-nums">
                            {trace.id.slice(0, 12)}
                          </span>
                          <span className="truncate text-sm">{trace.task || "Untitled"}</span>
                        </Command.Item>
                      ))}
                    </Command.Group>
                  )}

                  <Command.Group heading="Navigation" className={GROUP_HEADING}>
                    <Command.Item
                      value="Traces"
                      onSelect={() => { onNavigate("traces"); close(); }}
                      className={ITEM_CLASS}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-secondary">
                        <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
                      </svg>
                      <span>Traces</span>
                    </Command.Item>
                    <Command.Item
                      value="Stats"
                      onSelect={() => { onNavigate("stats"); close(); }}
                      className={ITEM_CLASS}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-secondary">
                        <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" />
                      </svg>
                      <span>Stats</span>
                    </Command.Item>
                  </Command.Group>

                  <Command.Group heading="Actions" className={GROUP_HEADING}>
                    <Command.Item
                      value="Export as JSON"
                      onSelect={() => { window.open("/api/traces?format=ndjson", "_blank"); close(); }}
                      className={ITEM_CLASS}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-secondary">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      <span>Export as JSON</span>
                    </Command.Item>
                  </Command.Group>
                </Command.List>
              </Command>
            </motion.div>
          </div>
        </div>
      )}
    </AnimatePresence>
  );
}
