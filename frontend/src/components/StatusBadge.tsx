const styles: Record<string, { dot: string; bg: string; text: string }> = {
  completed: { dot: "bg-success", bg: "bg-success-subtle", text: "text-success" },
  error: { dot: "bg-error", bg: "bg-error-subtle", text: "text-error" },
  timeout: { dot: "bg-warning", bg: "bg-warning-subtle", text: "text-warning" },
  cancelled: { dot: "bg-neutral", bg: "bg-surface", text: "text-secondary" },
};

const fallback = { dot: "bg-neutral", bg: "bg-surface", text: "text-secondary" };

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const s = styles[status] ?? fallback;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${s.bg} ${s.text}`}
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {status}
    </span>
  );
}
