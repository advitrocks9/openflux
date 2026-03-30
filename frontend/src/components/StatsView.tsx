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
  icon: React.ReactNode;
  accentClass?: string;
}

function MetricCard({ label, value, icon, accentClass = "text-accent" }: MetricCardProps) {
  return (
    <div className="group relative bg-surface border border-border rounded-xl p-4 hover:border-border-strong transition-colors duration-200 overflow-hidden">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary">
            {label}
          </div>
          <div className="text-2xl font-semibold text-primary font-mono tabular-nums mt-1.5">
            {value}
          </div>
        </div>
        <div className={`p-2 rounded-lg bg-surface ${accentClass}`}>
          {icon}
        </div>
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
    <div className="bg-surface border border-border rounded-lg px-3.5 py-2.5 shadow-xl text-xs">
      <div className="font-medium text-primary mb-1.5">{label}</div>
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-2 text-secondary">
          <span className="w-2 h-2 rounded-full bg-chart-indigo" />
          Input: <span className="font-mono text-primary">{formatTokens(input)}</span>
        </span>
        <span className="flex items-center gap-2 text-secondary">
          <span className="w-2 h-2 rounded-full bg-chart-indigo-light" />
          Output: <span className="font-mono text-primary">{formatTokens(output)}</span>
        </span>
      </div>
    </div>
  );
}

function TraceTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length || !label) return null;

  const count = payload.find((p) => p.dataKey === "traces")?.value ?? 0;

  return (
    <div className="bg-surface border border-border rounded-lg px-3.5 py-2.5 shadow-xl text-xs">
      <div className="font-medium text-primary mb-1">{label}</div>
      <span className="flex items-center gap-2 text-secondary">
        <span className="w-2 h-2 rounded-full bg-chart-emerald" />
        Traces: <span className="font-mono text-primary">{count}</span>
      </span>
    </div>
  );
}

function SkeletonCards() {
  return (
    <div className="grid grid-cols-4 gap-4 px-5 pt-5">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-24 bg-surface animate-pulse rounded-xl border border-border"
          style={{ animationDelay: `${i * 75}ms` }}
        />
      ))}
    </div>
  );
}

function SkeletonChart() {
  return (
    <div className="px-5 py-3">
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="h-4 w-48 bg-sunken animate-pulse rounded mb-4" />
        <div className="h-[260px] bg-sunken animate-pulse rounded-lg" />
      </div>
    </div>
  );
}

const CHART_INDIGO = "#6366f1";
const CHART_INDIGO_LIGHT = "#a5b4fc";
const CHART_EMERALD = "#34d399";
const GRID_COLOR = "rgba(128, 128, 128, 0.08)";
const TICK_COLOR = "rgba(128, 128, 128, 0.5)";

export function StatsView({ stats, timeline, loading }: StatsViewProps) {
  if (loading) {
    return (
      <div>
        <SkeletonCards />
        <SkeletonChart />
        <SkeletonChart />
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-secondary gap-3">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-tertiary">
          <line x1="18" y1="20" x2="18" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="6" y1="20" x2="6" y2="14" />
        </svg>
        <div className="text-sm">No data yet</div>
        <div className="text-xs text-tertiary">Traces will appear here once collected</div>
      </div>
    );
  }

  return (
    <div className="pb-6">
      <div className="grid grid-cols-4 gap-4 px-5 pt-5">
        <MetricCard
          label="Total Traces"
          value={formatWithCommas(stats.total_traces)}
          icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></svg>}
          accentClass="text-chart-emerald"
        />
        <MetricCard
          label="Input Tokens"
          value={formatTokens(stats.total_input_tokens)}
          icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" /></svg>}
          accentClass="text-chart-indigo"
        />
        <MetricCard
          label="Output Tokens"
          value={formatTokens(stats.total_output_tokens)}
          icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="17" y1="10" x2="3" y2="10" /><line x1="21" y1="6" x2="3" y2="6" /><line x1="21" y1="14" x2="3" y2="14" /><line x1="17" y1="18" x2="3" y2="18" /></svg>}
          accentClass="text-chart-indigo-light"
        />
        <MetricCard
          label="Est. Cost"
          value={formatCost(stats.total_input_tokens, stats.total_output_tokens)}
          icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></svg>}
          accentClass="text-chart-amber"
        />
      </div>

      <div className="px-5 pt-5">
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary mb-4">
            Token Usage (Last 30 Days)
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={timeline}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
              <XAxis dataKey="date" tickFormatter={formatDay} tick={{ fontSize: 10, fill: TICK_COLOR }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={formatTokens} tick={{ fontSize: 10, fill: TICK_COLOR }} axisLine={false} tickLine={false} width={52} />
              <Tooltip content={<TokenTooltip />} cursor={{ fill: "rgba(128, 128, 128, 0.06)" }} />
              <Bar dataKey="input_tokens" stackId="tokens" fill={CHART_INDIGO} radius={[0, 0, 0, 0]} />
              <Bar dataKey="output_tokens" stackId="tokens" fill={CHART_INDIGO_LIGHT} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="px-5 pt-4">
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-tertiary mb-4">
            Traces per Day
          </div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={timeline}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
              <XAxis dataKey="date" tickFormatter={formatDay} tick={{ fontSize: 10, fill: TICK_COLOR }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: TICK_COLOR }} axisLine={false} tickLine={false} width={36} allowDecimals={false} />
              <Tooltip content={<TraceTooltip />} cursor={{ fill: "rgba(128, 128, 128, 0.06)" }} />
              <Bar dataKey="traces" fill={CHART_EMERALD} radius={[3, 3, 0, 0]} maxBarSize={32} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
