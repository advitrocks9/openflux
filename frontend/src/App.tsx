import { useState, useEffect, useCallback, useMemo } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Layout } from "./components/Layout";
import { TraceTable } from "./components/TraceTable";
import { TraceDetail } from "./components/TraceDetail";
import { FilterBar } from "./components/FilterBar";
import { StatsView } from "./components/StatsView";
import { WasteView } from "./components/WasteView";
import { CommandPalette } from "./components/CommandPalette";
import { useTraces } from "./hooks/useTraces";
import { useTrace } from "./hooks/useTrace";
import { useStats } from "./hooks/useStats";
import { useKeyboard } from "./hooks/useKeyboard";

type View = "traces" | "stats" | "insights";

function getViewFromHash(): View {
  const h = window.location.hash;
  if (h === "#stats") return "stats";
  if (h === "#insights") return "insights";
  return "traces";
}

const PAGE_SIZE = 50;

export function App() {
  const [view, setView] = useState<View>(getViewFromHash);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [isDark, setIsDark] = useState(() => !document.body.classList.contains("light"));
  const [cmdkOpen, setCmdkOpen] = useState(false);

  const [statusFilter, setStatusFilter] = useState("");
  const [agentFilter, setAgentFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [sort, setSort] = useState("timestamp");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const {
    traces,
    total,
    loading: tracesLoading,
    page,
    setPage,
  } = useTraces({
    limit: PAGE_SIZE,
    status: statusFilter,
    agent: agentFilter,
    search: searchQuery,
    sort,
    order,
  });

  const { trace: selectedTrace, loading: traceLoading } =
    useTrace(selectedTraceId);

  const { stats, timeline, loading: statsLoading } = useStats();

  const agents = useMemo(() => {
    const set = new Set(traces.map((t) => t.agent));
    return Array.from(set).sort();
  }, [traces]);

  useEffect(() => {
    function onHashChange() {
      setView(getViewFromHash());
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const handleViewChange = useCallback((v: View) => {
    window.location.hash = v === "traces" ? "#traces" : `#${v}`;
    setView(v);
    setSelectedTraceId(null);
  }, []);

  const handleToggleDark = useCallback(() => {
    setIsDark((prev) => {
      const next = !prev;
      document.body.classList.toggle("light", !next);
      return next;
    });
  }, []);

  const handleSort = useCallback(
    (column: string, newOrder: "asc" | "desc") => {
      setSort(column);
      setOrder(newOrder);
    },
    [],
  );

  const handleCloseDetail = useCallback(() => {
    setSelectedTraceId(null);
  }, []);

  useKeyboard({
    Escape: handleCloseDetail,
    "Meta+k": () => setCmdkOpen(true),
  });

  return (
    <>
      <Layout
        view={view}
        onViewChange={handleViewChange}
        onToggleDark={handleToggleDark}
        isDark={isDark}
      >
        {view === "traces" ? (
          <div className="flex flex-1 min-h-0 overflow-hidden">
            <div
              className={`flex flex-col ${selectedTraceId ? "flex-1 min-w-0" : "w-full"} transition-all duration-200`}
            >
              <FilterBar
                status={statusFilter}
                agent={agentFilter}
                search={searchQuery}
                agents={agents}
                onStatusChange={setStatusFilter}
                onAgentChange={setAgentFilter}
                onSearchChange={setSearchQuery}
              />
              <div className="flex-1 overflow-auto">
                <TraceTable
                  traces={traces}
                  loading={tracesLoading}
                  total={total}
                  page={page}
                  pageSize={PAGE_SIZE}
                  selectedId={selectedTraceId}
                  onSelect={setSelectedTraceId}
                  onPageChange={setPage}
                  onSort={handleSort}
                  sort={sort}
                  order={order}
                />
              </div>
            </div>
            <AnimatePresence>
              {selectedTraceId && (
                <motion.div
                  initial={{ width: 0, opacity: 0 }}
                  animate={{ width: 520, opacity: 1 }}
                  exit={{ width: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: "easeOut" }}
                  className="flex-shrink-0 border-l border-border overflow-hidden"
                >
                  <div className="w-[520px] h-full">
                    <TraceDetail
                      trace={selectedTrace}
                      loading={traceLoading}
                      onClose={handleCloseDetail}
                    />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        ) : view === "stats" ? (
          <div className="overflow-auto flex-1 min-h-0">
            <StatsView
              stats={stats}
              timeline={timeline}
              loading={statsLoading}
            />
          </div>
        ) : (
          <WasteView />
        )}
      </Layout>
      <CommandPalette
        open={cmdkOpen}
        onOpenChange={setCmdkOpen}
        traces={traces.slice(0, 5)}
        onSelectTrace={(id) => {
          setSelectedTraceId(id);
          handleViewChange("traces");
          setCmdkOpen(false);
        }}
        onNavigate={(v) => {
          handleViewChange(v);
          setCmdkOpen(false);
        }}
      />
    </>
  );
}
