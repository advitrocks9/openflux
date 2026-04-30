import type { Outcome } from "../types";
import { useOutcomes } from "../hooks/useOutcomes";

function shortSha(sha: string | null): string {
  if (!sha) return "—";
  return sha.slice(0, 7);
}

function estimateCost(o: Outcome): string {
  if (!o.trace) return "—";
  const input = o.trace.token_input + o.trace.token_cache_creation;
  const output = o.trace.token_output;
  // Rough Sonnet-class blended rate: $3/M in, $15/M out
  const cost = (input * 3 + output * 15) / 1_000_000;
  return `$${cost.toFixed(2)}`;
}

function TestsBadge({ passed }: { passed: boolean | null }) {
  if (passed === true) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded bg-green-500/10 text-green-500">
        ✓ pass
      </span>
    );
  }
  if (passed === false) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded bg-red-500/10 text-red-500">
        ✗ fail
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded bg-surface text-tertiary">
      —
    </span>
  );
}

function ShippedBadge({ outcome }: { outcome: Outcome }) {
  const shipped = outcome.lines_added > 0 && outcome.tests_passed !== false;
  if (shipped && outcome.tests_passed === true) {
    return (
      <span className="text-[10px] font-medium uppercase tracking-wider text-green-500">
        shipped
      </span>
    );
  }
  if (outcome.tests_passed === false) {
    return (
      <span className="text-[10px] font-medium uppercase tracking-wider text-red-500">
        broke tests
      </span>
    );
  }
  if (outcome.lines_added === 0) {
    return (
      <span className="text-[10px] font-medium uppercase tracking-wider text-tertiary">
        no diff
      </span>
    );
  }
  return (
    <span className="text-[10px] font-medium uppercase tracking-wider text-secondary">
      changed
    </span>
  );
}

function formatTimestamp(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleString();
}

export function SessionsView() {
  const { outcomes, loading, error } = useOutcomes(100);

  if (loading) {
    return (
      <div className="p-8 text-tertiary text-sm">Loading sessions…</div>
    );
  }

  if (error) {
    return (
      <div className="p-8 text-red-500 text-sm">
        Failed to load: {error}
      </div>
    );
  }

  if (outcomes.length === 0) {
    return (
      <div className="p-8 max-w-2xl">
        <div className="text-primary text-sm font-medium mb-2">
          No sessions yet.
        </div>
        <div className="text-tertiary text-sm space-y-2">
          <p>
            Sessions appear here after Claude Code runs in a git repo with
            OpenFlux hooks installed. To see outcomes (tests passed / lines
            shipped), set:
          </p>
          <pre className="bg-surface border border-border rounded-md p-3 text-[11px] font-mono text-secondary overflow-x-auto">
{`export OPENFLUX_TEST_CMD="pytest -q"
openflux install --hooks`}
          </pre>
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-auto h-full">
      <div className="p-5">
        <div className="flex items-baseline justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-primary">Sessions</h2>
            <p className="text-xs text-tertiary mt-0.5">
              Did this Claude Code session ship working code?
            </p>
          </div>
          <div className="text-[10px] font-mono tabular-nums text-tertiary">
            {outcomes.length} {outcomes.length === 1 ? "session" : "sessions"}
          </div>
        </div>

        <div className="bg-surface border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left text-[10px] font-semibold uppercase tracking-widest text-tertiary px-4 py-2.5">
                  When
                </th>
                <th className="text-left text-[10px] font-semibold uppercase tracking-widest text-tertiary px-4 py-2.5">
                  Outcome
                </th>
                <th className="text-right text-[10px] font-semibold uppercase tracking-widest text-tertiary px-4 py-2.5">
                  Cost
                </th>
                <th className="text-right text-[10px] font-semibold uppercase tracking-widest text-tertiary px-4 py-2.5">
                  Lines
                </th>
                <th className="text-right text-[10px] font-semibold uppercase tracking-widest text-tertiary px-4 py-2.5">
                  Files
                </th>
                <th className="text-left text-[10px] font-semibold uppercase tracking-widest text-tertiary px-4 py-2.5">
                  Tests
                </th>
                <th className="text-left text-[10px] font-semibold uppercase tracking-widest text-tertiary px-4 py-2.5">
                  Diff
                </th>
                <th className="text-left text-[10px] font-semibold uppercase tracking-widest text-tertiary px-4 py-2.5">
                  Task
                </th>
              </tr>
            </thead>
            <tbody>
              {outcomes.map((o) => (
                <tr
                  key={`${o.session_id}-${o.agent}`}
                  className="border-b border-border last:border-0 hover:bg-background/50 transition-colors"
                >
                  <td className="px-4 py-2.5 text-[11px] text-secondary font-mono tabular-nums">
                    {formatTimestamp(o.captured_at)}
                  </td>
                  <td className="px-4 py-2.5">
                    <ShippedBadge outcome={o} />
                  </td>
                  <td className="px-4 py-2.5 text-right text-secondary font-mono tabular-nums">
                    {estimateCost(o)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums">
                    <span className="text-green-500">+{o.lines_added}</span>
                    <span className="text-tertiary mx-0.5">/</span>
                    <span className="text-red-500">-{o.lines_removed}</span>
                  </td>
                  <td className="px-4 py-2.5 text-right text-secondary font-mono tabular-nums">
                    {o.files_changed}
                  </td>
                  <td className="px-4 py-2.5">
                    <TestsBadge passed={o.tests_passed} />
                  </td>
                  <td className="px-4 py-2.5 text-[11px] font-mono text-tertiary">
                    {shortSha(o.start_sha)} → {shortSha(o.end_sha)}
                  </td>
                  <td className="px-4 py-2.5 text-secondary truncate max-w-xs">
                    {o.trace?.task ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {outcomes.length > 0 && (
          <div className="mt-4 text-[11px] text-tertiary">
            Cost is estimated using a Sonnet-class blended rate ($3/M in, $15/M out) and may diverge from your actual Anthropic invoice. Tokens come from the joined trace; lines and tests are captured at session start/end. Configure your test command via{" "}
            <code className="px-1 py-0.5 rounded bg-surface text-secondary">
              OPENFLUX_TEST_CMD
            </code>
            .
          </div>
        )}
      </div>
    </div>
  );
}

