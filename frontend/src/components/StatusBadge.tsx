const dotColors: Record<string, string> = {
  completed: "bg-success",
  error: "bg-error",
  timeout: "bg-warning",
  cancelled: "bg-neutral",
};

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const dotColor = dotColors[status] ?? "bg-neutral";

  return (
    <span className="flex items-center gap-1.5 text-xs text-secondary">
      <span className={`inline-block h-2 w-2 rounded-full ${dotColor}`} />
      {status}
    </span>
  );
}
