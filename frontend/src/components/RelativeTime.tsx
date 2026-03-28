import { formatAbsoluteTime, formatRelativeTime } from "../lib/format";

interface RelativeTimeProps {
  iso: string;
}

export function RelativeTime({ iso }: RelativeTimeProps) {
  return (
    <time
      dateTime={iso}
      title={formatAbsoluteTime(iso)}
      className="text-xs text-secondary"
    >
      {formatRelativeTime(iso)}
    </time>
  );
}
