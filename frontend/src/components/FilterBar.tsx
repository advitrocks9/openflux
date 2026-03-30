import { useCallback, useEffect, useRef, useState } from "react";

interface FilterBarProps {
  status: string;
  agent: string;
  search: string;
  agents: string[];
  onStatusChange: (s: string) => void;
  onAgentChange: (a: string) => void;
  onSearchChange: (q: string) => void;
}

const STATUS_CHIPS = [
  { label: "All", value: "" },
  { label: "Completed", value: "completed" },
  { label: "Error", value: "error" },
  { label: "Timeout", value: "timeout" },
] as const;

export function FilterBar({
  status,
  agent,
  search,
  agents,
  onStatusChange,
  onAgentChange,
  onSearchChange,
}: FilterBarProps) {
  const [localSearch, setLocalSearch] = useState(search);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchInput = useCallback(
    (value: string) => {
      setLocalSearch(value);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => onSearchChange(value), 300);
    },
    [onSearchChange],
  );

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  useEffect(() => {
    setLocalSearch(search);
  }, [search]);

  return (
    <div className="flex items-center gap-3 border-b border-border px-5 py-2.5">
      <div className="flex items-center gap-1">
        {STATUS_CHIPS.map((chip) => {
          const isActive = status === chip.value;
          return (
            <button
              key={chip.value}
              type="button"
              onClick={() => onStatusChange(chip.value)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer transition-all duration-200 ${
                isActive
                  ? "bg-accent text-white shadow-sm"
                  : "text-secondary hover:text-primary hover:bg-surface"
              }`}
            >
              {chip.label}
            </button>
          );
        })}
      </div>

      <div className="h-4 w-px bg-border" />

      <div className="relative">
        <select
          value={agent}
          onChange={(e) => onAgentChange(e.target.value)}
          className="appearance-none rounded-md border border-border bg-surface pl-2.5 pr-7 py-1 text-xs text-primary cursor-pointer hover:bg-surface-hover transition-colors duration-200"
        >
          <option value="">All agents</option>
          {agents.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <svg
          className="pointer-events-none absolute right-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-tertiary"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      <div className="flex-1" />

      <div className="relative">
        <svg
          className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-tertiary"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          value={localSearch}
          onChange={(e) => handleSearchInput(e.target.value)}
          placeholder="Search traces..."
          className="w-56 rounded-md border border-border bg-surface py-1.5 pl-9 pr-3 text-sm text-primary placeholder:text-tertiary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-all duration-200"
        />
      </div>
    </div>
  );
}
