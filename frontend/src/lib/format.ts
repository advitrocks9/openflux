export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function formatDuration(ms: number): string {
  if (ms < 1_000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(1)}s`;
  const mins = Math.floor(ms / 60_000);
  const secs = Math.round((ms % 60_000) / 1_000);
  return `${mins}m ${secs}s`;
}

export function formatRelativeTime(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diff = now - then;

  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) {
    const mins = Math.floor(diff / 60_000);
    return `${mins}m ago`;
  }
  if (diff < 86_400_000) {
    const hours = Math.floor(diff / 3_600_000);
    return `${hours}h ago`;
  }
  const days = Math.floor(diff / 86_400_000);
  return `${days}d ago`;
}

export function formatAbsoluteTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + "\u2026";
}

export function estimateCost(
  inputTokens: number,
  outputTokens: number,
  model: string,
): number {
  // Per million tokens
  const rates: Record<string, [number, number]> = {
    "claude-sonnet": [3, 15],
    "claude-opus": [15, 75],
    "claude-haiku": [0.25, 1.25],
    "gpt-4o": [2.5, 10],
    "gpt-4o-mini": [0.15, 0.6],
    "gemini-2.0-flash": [0.075, 0.3],
    "gemini-2.5-pro": [1.25, 10],
  };

  const key = Object.keys(rates).find((k) => model.includes(k));
  const [inRate, outRate] = key ? rates[key] : [1, 4];
  return (inputTokens * inRate + outputTokens * outRate) / 1_000_000;
}
