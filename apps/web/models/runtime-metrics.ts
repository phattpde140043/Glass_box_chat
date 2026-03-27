export type RuntimeMetrics = {
  total_runs: number;
  total_nodes_executed: number;
  cache_hits: number;
  cache_misses: number;
  timeouts: number;
  retries: number;
  fallback_routes: number;
  avg_node_duration_ms: number;
  last_execution_mode: string;
  last_dag_node_count: number;
  last_completed_at: string | null;
  breaker_states: Record<string, boolean>;
};

export const EMPTY_RUNTIME_METRICS: RuntimeMetrics = {
  total_runs: 0,
  total_nodes_executed: 0,
  cache_hits: 0,
  cache_misses: 0,
  timeouts: 0,
  retries: 0,
  fallback_routes: 0,
  avg_node_duration_ms: 0,
  last_execution_mode: "sequential",
  last_dag_node_count: 0,
  last_completed_at: null,
  breaker_states: {},
};
