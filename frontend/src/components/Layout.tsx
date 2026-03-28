import type { ReactNode } from "react";

interface LayoutProps {
  children: ReactNode;
  view: "traces" | "stats";
  onViewChange: (v: "traces" | "stats") => void;
  onToggleDark: () => void;
  isDark: boolean;
}

const tabs = [
  { key: "traces" as const, label: "Traces" },
  { key: "stats" as const, label: "Stats" },
];

export function Layout({
  children,
  view,
  onViewChange,
  onToggleDark,
  isDark,
}: LayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-background text-primary">
      <header className="h-12 shrink-0 flex items-center justify-between px-4 border-b border-border">
        {/* Left: logo */}
        <span className="font-semibold text-sm tracking-tight">OpenFlux</span>

        {/* Center: nav tabs */}
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => onViewChange(tab.key)}
              className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                view === tab.key
                  ? "text-accent border-b-2 border-accent"
                  : "text-secondary hover:text-primary"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Right: dark toggle + keyboard hint */}
        <div className="flex items-center gap-2">
          <button
            onClick={onToggleDark}
            className="p-1.5 rounded text-secondary hover:text-primary hover:bg-surface transition-colors"
            aria-label="Toggle dark mode"
          >
            {isDark ? (
              // Sun icon
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
              // Moon icon
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
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            )}
          </button>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-mono text-tertiary bg-sunken border border-border rounded">
            <span>&#8984;</span>K
          </kbd>
        </div>
      </header>

      <main className="flex-1 overflow-hidden">{children}</main>
    </div>
  );
}
