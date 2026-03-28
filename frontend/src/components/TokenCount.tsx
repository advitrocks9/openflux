import { formatTokens } from "../lib/format";
import type { TokenUsage } from "../types";

interface TokenCountProps {
  usage: TokenUsage | null;
}

export function TokenCount({ usage }: TokenCountProps) {
  if (!usage) {
    return <span className="text-xs text-tertiary">--</span>;
  }

  return (
    <span className="font-mono text-xs tabular-nums">
      {formatTokens(usage.input_tokens)} / {formatTokens(usage.output_tokens)}
    </span>
  );
}
