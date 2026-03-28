import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { StatsResponse, TimelineEntry } from "../types";
import { formatTokens } from "../lib/format";

interface StatsViewProps {
  stats: StatsResponse | null;
  timeline: TimelineEntry[];
  loading: boolean;
}

function formatDay(day: string): string {
  const d = new Date(day);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function formatCost(input: number, output: number): string {
  const cost = (input + output * 4) / 1_000_000;
  return `$${cost.toFixed(2)}`;
}

function formatWithCommas(n: number): string {
  return n.toLocaleString();
}

interface MetricCardProps {
  label: string;
  value: string;
}

function MetricCard({ label, value }: MetricCardProps) {
  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="text-xs font-medium uppercase tracking-wider text-tertiary">
        {label}
      </div>
      <div className="text-2xl font-semibold text-primary font-mono tabular-nums mt-1">
        {value}
      </div>
    </div>
  );
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    value: number;
    dataKey: string;
    color: string;
  }>;
  label?: string;
}

function TokenTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length || !label) return null;

  const input = payload.find((p) => p.dataKey === "input_tokens")?.value ?? 0;
  const output = payload.find((p) => p.dataKey === "output_tokens")?.value ?? 0;

  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 shadow-lg text-xs">
      <div className="font-medium text-primary mb-1">{label}</div>
      <div className="flex flex-col gap-0.5">
        <span className="text-secondary">
          Input: <span className="font-mono text-primary">{formatTokens(input)}</span>
        </span>
        <span className="text-secondary">
          Output: <span className="font-mono text-primary">{formatTokens(output)}</span>
        </span>
      </div>
    </div>
  );
}

function TraceTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length || !label) return null;

  const count = payload.find((p) => p.dataKey === "count")?.value ?? 0;

  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 shadow-lg text-xs">
      <div className="font-medium text-primary mb-1">{label}</div>
      <span className="text-secondary">
        Traces: <span className="font-mono text-primary">{count}</span>
      </span>
    </div>
  );
}

function SkeletonCards() {
  return (
    <div className="grid grid-cols-4 gap-4 px-4 py-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-20 bg-surface animate-pulse rounded-lg border border-border"
        />
      ))}
    </div>
  );
}

function SkeletonChart() {
  return (
    <div className="px-4 py-2">
      <div className="bg-surface border border-border rounded-lg p-4">
        <div className="h-4 w-48 bg-sunken animate-pulse rounded mb-3" />
        <div className="h-[280px] bg-sunken animate-pulse rounded" />
      </div>
    </div>
  );
}

export function StatsView({ stats, timeline, loading }: StatsViewProps) {
  if (loading) {
    return (
      <div>
        <SkeletonCards />
        <SkeletonChart />
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-64 text-secondary text-sm">
        No data
      </div>
    );
  }

  return (
    <div>
      {/* Top metrics row */}
      <div className="grid grid-cols-4 gap-4 px-4 py-4">
        <MetricCard
          label="Total Traces"
          value={formatWithCommas(stats.total_traces)}
        />
        <MetricCard
          label="Input Tokens"
          value={formatTokens(stats.total_input_tokens)}
        />
        <MetricCard
          label="Output Tokens"
          value={formatTokens(stats.total_output_tokens)}
        />
        <MetricCard
          label="Est. Cost"
          value={formatCost(stats.total_input_tokens, stats.total_output_tokens)}
        />
      </div>

      {/* Token usage timeline chart */}
      <div className="px-4 py-2">
        <div className="bg-surface border border-border rounded-lg p-4">
          <div className="text-xs font-medium uppercase tracking-wider text-tertiary mb-3">
            Token Usage (Last 30 Days)
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={timeline}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="oklch(0 0 0 / 0.04)"
                vertical={false}
              />
              <XAxis
                dataKey="day"
                tickFormatter={formatDay}
                tick={{ fontSize: 11, fill: "oklch(0.6 0 0)" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={formatTokens}
                tick={{ fontSize: 11, fill: "oklch(0.6 0 0)" }}
                axisLine={false}
                tickLine={false}
                width={56}
              />
              <Tooltip content={<TokenTooltip />} cursor={{ fill: "oklch(0 0 0 / 0.03)" }} />
              <Bar
                dataKey="input_tokens"
                stackId="tokens"
                fill="#6366f1"
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="output_tokens"
                stackId="tokens"
                fill="#a5b4fc"
                radius={[2, 2, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Daily trace count chart */}
      <div className="px-4 py-2">
        <div className="bg-surface border border-border rounded-lg p-4">
          <div className="text-xs font-medium uppercase tracking-wider text-tertiary mb-3">
            Traces per Day
          </div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={timeline}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="oklch(0 0 0 / 0.04)"
                vertical={false}
              />
              <XAxis
                dataKey="day"
                tickFormatter={formatDay}
                tick={{ fontSize: 11, fill: "oklch(0.6 0 0)" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "oklch(0.6 0 0)" }}
                axisLine={false}
                tickLine={false}
                width={40}
                allowDecimals={false}
              />
              <Tooltip content={<TraceTooltip />} cursor={{ fill: "oklch(0 0 0 / 0.03)" }} />
              <Bar dataKey="count" fill="#6366f1" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
