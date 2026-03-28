import { useState, useEffect, useCallback } from "react";
import { Layout } from "./components/Layout";

type View = "traces" | "stats";

function getViewFromHash(): View {
  return window.location.hash === "#stats" ? "stats" : "traces";
}

export function App() {
  const [view, setView] = useState<View>(getViewFromHash);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [isDark, setIsDark] = useState(
    () => document.body.classList.contains("dark"),
  );

  // Sync hash -> view
  useEffect(() => {
    function onHashChange() {
      setView(getViewFromHash());
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const handleViewChange = useCallback((v: View) => {
    window.location.hash = v === "stats" ? "#stats" : "#traces";
    setView(v);
    setSelectedTraceId(null);
  }, []);

  const handleToggleDark = useCallback(() => {
    setIsDark((prev) => {
      const next = !prev;
      document.body.classList.toggle("dark", next);
      return next;
    });
  }, []);

  return (
    <Layout
      view={view}
      onViewChange={handleViewChange}
      onToggleDark={handleToggleDark}
      isDark={isDark}
    >
      {view === "traces" ? (
        <div className="flex h-full">
          <div className={selectedTraceId ? "w-1/2" : "w-full"}>
            {/* TraceTable will go here */}
            <div className="p-4 text-secondary text-sm">
              Traces view — TraceTable pending
            </div>
          </div>
          {selectedTraceId && (
            <div className="w-1/2 border-l border-border overflow-y-auto">
              {/* TraceDetail will go here */}
              <div className="p-4 text-secondary text-sm">
                Detail: {selectedTraceId}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="p-4 text-secondary text-sm">
          Stats view — StatsView pending
        </div>
      )}
    </Layout>
  );
}
