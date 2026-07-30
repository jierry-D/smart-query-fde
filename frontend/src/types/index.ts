/* Type definitions */

export interface User {
  user_id: number;
  username: string;
  display_name: string;
  role: 'admin' | 'leader' | 'employee';
  department: string;
  region: string;
  position?: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: User;
}

export interface ChatResponse {
  type: 'number' | 'table' | 'error' | 'pending' | 'clarify'
    | 'metric_list' | 'snapshot_list' | 'db_status' | 'help'
    | 'metric_detail' | 'import_result' | 'report';
  metric_name?: string;
  value?: number;
  unit?: string;
  explanation?: string;
  formula?: string;
  sql?: string;
  columns?: string[];
  rows?: Record<string, unknown>[];
  process?: StageInfo[];
  time_intelligence?: TimeIntel;
  drill_down?: DrillDown[];
  clarification?: ClarifyOption[];
  elapsed_ms?: number;
  row_count?: number;
  message?: string;
  // Report fields
  report?: string;
  sections?: string[];
  queries_executed?: number;
}

export interface StageInfo {
  name: string;
  status: 'running' | 'done' | 'error';
  elapsed_ms: number;
  detail?: string;
}

export interface TimeIntel {
  available: boolean;
  label: string;
  previous_value: number;
  current_value: number;
  growth_rate: number;
  direction: 'increase' | 'decrease' | 'stable';
}

export interface DrillDown {
  label: string;
  query: string;
}

export interface ClarifyOption {
  label: string;
  query: string;
}

export interface MetricItem {
  id: number;
  name: string;
  category: string;
  status: 'available' | 'pending';
  unit?: string;
  description?: string;
}

export interface SnapshotItem {
  snapshot_id: number;
  table_name: string;
  data_period: string;
  ingestion_time: string;
  description: string;
}

export interface StatusInfo {
  date: string;
  version: string;
  tables: number;
  snapshots: number;
  metrics_total: number;
  metrics_available: number;
  users: number;
  db_type: string;
}

export interface AdminStats {
  total_queries: number;
  unique_users: number;
  accuracy: number;
  avg_latency_ms: number;
  top_queries: { query: string; count: number }[];
}

export interface QueryLog {
  id: number;
  username: string;
  original_query: string;
  generated_sql: string;
  exec_time_ms: number;
  status: string;
  created_at: string;
}
