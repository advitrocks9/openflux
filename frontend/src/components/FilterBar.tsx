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
    <div className="flex items-center gap-3 border-b border-border px-4 py-2">
      {/* Status chips */}
      <div className="flex items-center gap-1.5">
        {STATUS_CHIPS.map((chip) => (
          <button
            key={chip.value}
            type="button"
            onClick={() => onStatusChange(chip.value)}
            className={
              status === chip.value
                ? "rounded bg-accent px-2.5 py-1 text-xs font-medium text-white"
                : "cursor-pointer rounded bg-surface px-2.5 py-1 text-xs font-medium text-secondary transition-colors duration-150 hover:bg-accent-subtle"
            }
          >
            {chip.label}
          </button>
        ))}
      </div>

      {/* Agent dropdown */}
      <select
        value={agent}
        onChange={(e) => onAgentChange(e.target.value)}
        className="rounded border border-border bg-surface px-2 py-1 text-xs text-primary"
      >
        <option value="">All agents</option>
        {agents.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Search input */}
      <div className="relative">
        <svg
          className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-tertiary"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="7" cy="7" r="5" />
          <path d="M11 11l3.5 3.5" />
        </svg>
        <input
          type="text"
          value={localSearch}
          onChange={(e) => handleSearchInput(e.target.value)}
          placeholder="Search traces..."
          className="w-64 rounded-md border border-border bg-surface py-1.5 pl-8 pr-3 text-sm text-primary placeholder:text-tertiary"
        />
      </div>
    </div>
  );
}
