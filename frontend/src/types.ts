export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
}

export interface ContextRecord {
  context_type: string;
  source: string;
  content: string;
  content_hash: string;
}

export interface SearchRecord {
  query: string;
  engine: string;
  results_count: number;
}

export interface SourceRecord {
  path: string;
  source_type: string;
  content: string;
  content_hash: string;
  byte_size: number;
}

export interface ToolRecord {
  tool_name: string;
  tool_input: string;
  tool_output: string;
  duration_ms: number;
  error: boolean;
}

export interface Trace {
  id: string;
  timestamp: string;
  agent: string;
  session_id: string;
  parent_id: string | null;
  model: string;
  task: string;
  decision: string;
  status: string;
  correction: string | null;
  scope: string | null;
  tags: string[];
  context: ContextRecord[];
  searches: SearchRecord[];
  sources_read: SourceRecord[];
  tools_used: ToolRecord[];
  files_modified: string[];
  turn_count: number;
  token_usage: TokenUsage | null;
  duration_ms: number;
  metadata: Record<string, unknown>;
  schema_version: string;
}

export interface TracesResponse {
  traces: Trace[];
  total: number;
  limit: number;
  offset: number;
}

export interface StatsResponse {
  total_traces: number;
  total_input_tokens: number;
  total_output_tokens: number;
  latest_timestamp: string | null;
}

export interface TimelineEntry {
  date: string;
  traces: number;
  input_tokens: number;
  output_tokens: number;
}

export interface TimelineResponse {
  days: TimelineEntry[];
}

export interface TraceStats {
  tool_count: number;
  search_count: number;
  source_count: number;
  files_modified_count: number;
}

// Waste detection types

export interface LoopSession {
  trace_id: string;
  task: string;
  cost: number;
  loop_start_index: number;
  total_tools: number;
  cycle_count: number;
  productive_cost: number;
  loop_cost: number;
}

export interface ErrorSummary {
  total_cost: number;
  total_count: number;
  fast_errors: number;
  fast_error_cost: number;
  slow_errors: number;
  slow_error_cost: number;
}

export interface ReloadSummary {
  total_cost: number;
  count: number;
}

export interface WasteReport {
  total_sessions: number;
  total_cost: number;
  productive_cost: number;
  loops: LoopSession[];
  loop_cost: number;
  errors: ErrorSummary;
  reloads: ReloadSummary;
}

export interface ToolStep {
  index: number;
  name: string;
  target: string;
  error: boolean;
  output_summary: string;
  timestamp: string;
}

export interface SessionReplay {
  trace_id: string;
  task: string;
  status: string;
  model: string;
  turn_count: number;
  duration_ms: number;
  total_cost: number;
  tools: ToolStep[];
  loop_start: number | null;
  loop_cycles: number;
  productive_cost: number;
  loop_cost: number;
  scope: string;
}
