import type { ReactNode } from "react";

interface LayoutProps {
  children: ReactNode;
  view: "traces" | "sessions" | "stats" | "insights";
  onViewChange: (v: "traces" | "sessions" | "stats" | "insights") => void;
  onToggleDark: () => void;
  isDark: boolean;
}

const tabs = [
  {
    key: "traces" as const,
    label: "Traces",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    ),
  },
  {
    key: "sessions" as const,
    label: "Sessions",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
  },
  {
    key: "stats" as const,
    label: "Stats",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </svg>
    ),
  },
  {
    key: "insights" as const,
    label: "Insights",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="1" x2="12" y2="23" />
        <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
      </svg>
    ),
  },
];

function FluxIcon({ isDark }: { isDark: boolean }) {
  return (
    <img
      src="/logo.png"
      alt="OpenFlux"
      width={22}
      height={22}
      className={`rounded-md ${isDark ? "brightness-110 contrast-110" : ""}`}
      style={isDark ? { filter: "drop-shadow(0 0 1px rgba(129,140,248,0.3))" } : undefined}
    />
  );
}

export function Layout({
  children,
  view,
  onViewChange,
  onToggleDark,
  isDark,
}: LayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-background text-primary">
      <header className="h-13 shrink-0 flex items-center justify-between px-5 border-b border-border backdrop-blur-xl bg-background/80 sticky top-0 z-30">
        <div className="flex items-center gap-2.5">
          <FluxIcon isDark={isDark} />
          <span className="font-semibold text-sm tracking-tight text-primary">
            OpenFlux
          </span>
        </div>

        <nav className="flex items-center gap-0.5 rounded-lg bg-surface p-0.5">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => onViewChange(tab.key)}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-md cursor-pointer transition-all duration-200 ${
                view === tab.key
                  ? "bg-accent-subtle text-accent shadow-sm"
                  : "text-secondary hover:text-primary"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-1.5">
          <kbd className="hidden sm:inline-flex items-center gap-0.5 px-2 py-1 text-[10px] font-mono text-tertiary bg-surface border border-border rounded-md cursor-default select-none">
            <span>&#8984;</span>K
          </kbd>
          <button
            onClick={onToggleDark}
            className="p-2 rounded-md text-tertiary hover:text-primary hover:bg-surface transition-colors duration-200 cursor-pointer"
            aria-label="Toggle theme"
          >
            {isDark ? (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="5" />
                <line x1="12" y1="1" x2="12" y2="3" />
                <line x1="12" y1="21" x2="12" y2="23" />
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                <line x1="1" y1="12" x2="3" y2="12" />
                <line x1="21" y1="12" x2="23" y2="12" />
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
              </svg>
            ) : (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            )}
          </button>
        </div>
      </header>

      <main className="flex-1 flex flex-col overflow-hidden min-h-0">{children}</main>
    </div>
  );
}
