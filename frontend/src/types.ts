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

export interface OutcomeTraceSummary {
  trace_id: string;
  task: string;
  model: string;
  duration_ms: number;
  token_input: number;
  token_output: number;
  token_cache_read: number;
  token_cache_creation: number;
}

export interface Outcome {
  session_id: string;
  agent: string;
  start_sha: string | null;
  end_sha: string | null;
  lines_added: number;
  lines_removed: number;
  files_changed: number;
  tests_exit_code: number | null;
  tests_passed: boolean | null;
  pr_url: string | null;
  pr_merged: boolean | null;
  captured_at: string;
  trace: OutcomeTraceSummary | null;
}

export interface OutcomesResponse {
  outcomes: Outcome[];
  limit: number;
  count: number;
}
