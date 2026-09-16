/**
 * Typed API client.
 *
 * Every mutating request carries the CSRF token that /auth/login handed back,
 * matching the double-submit check the backend enforces in get_principal.
 */

import type { ThemeInfo } from '@/theme/themeLoader'

export type Role = 'viewer' | 'operator' | 'admin'
export type AuthMode = 'local' | 'oidc' | 'none'

export interface Meta {
  app_name: string
  version: string
  auth_mode: AuthMode
  insecure_no_auth: boolean
  read_only: boolean
  masking_enabled: boolean
  mask_presets: string[]
  prometheus_enabled: boolean
  sampler_enabled: boolean
  default_locale: string
  available_locales: string[]
  signup_available: boolean
  signup_is_first_user: boolean
  cluster_count: number
  theme: ThemeInfo
}

export interface Me {
  username: string
  role: Role
  provider: string
  csrf_token: string
}

export interface ClusterSummary {
  name: string
  label: string
  security_protocol: string
  sasl_mechanism: string | null
  has_schema_registry: boolean
  read_only: boolean
  masking_enabled: boolean
  reachable: boolean | null
}


// --- M2: cluster, topics, consumer groups ---------------------------------

export interface Degraded {
  reason: 'unreachable' | 'timeout' | 'auth_failed' | 'unsupported' | 'not_authorized' | 'unknown'
  message: string
  hint: string | null
}

export type Capability =
  | 'describe_cluster' | 'describe_configs' | 'alter_configs'
  | 'create_topics' | 'delete_topics' | 'create_partitions'
  | 'list_groups' | 'describe_groups' | 'delete_groups'
  | 'list_group_offsets' | 'alter_group_offsets' | 'list_offsets'
  | 'describe_acls' | 'alter_acls' | 'elect_leaders' | 'describe_log_dirs'

export interface Broker {
  id: number
  host: string
  port: number
  rack: string | null
  is_controller: boolean
}

export interface ClusterInfo {
  name: string
  label: string
  cluster_id: string | null
  mode: 'kraft' | 'zookeeper' | 'unknown'
  brokers: Broker[]
  controller_id: number | null
  topic_count: number
  internal_topic_count: number
  partition_count: number
  internal_partition_count: number
  under_replicated_partitions: number
  offline_partitions: number
  capabilities: Capability[]
  read_only: boolean
  degraded: Degraded | null
}

export interface TopicSummary {
  name: string
  partition_count: number
  replication_factor: number
  is_internal: boolean
  under_replicated_partitions: number
  offline_partitions: number
  message_count: number | null
  retention_ms: number | null
  cleanup_policy: string | null
}

export interface PartitionInfo {
  partition: number
  leader: number | null
  replicas: number[]
  in_sync_replicas: number[]
  low_watermark: number | null
  high_watermark: number | null
}

export interface TopicDetail {
  name: string
  is_internal: boolean
  partitions: PartitionInfo[]
  replication_factor: number
  message_count: number | null
  consumer_groups: string[]
  degraded: Degraded | null
}

export interface ConfigEntry {
  name: string
  value: string | null
  source: string
  is_default: boolean
  is_read_only: boolean
  is_sensitive: boolean
  documentation: string | null
}

export type GroupState =
  | 'unknown' | 'preparing_rebalance' | 'completing_rebalance'
  | 'stable' | 'dead' | 'empty'

export interface GroupSummary {
  group_id: string
  state: GroupState
  is_simple: boolean
  member_count: number
  topics: string[]
  total_lag: number | null
}

export interface GroupMemberAssignment { topic: string; partitions: number[] }

export interface GroupMember {
  member_id: string
  client_id: string | null
  host: string | null
  group_instance_id: string | null
  assignments: GroupMemberAssignment[]
}

export interface PartitionLag {
  topic: string
  partition: number
  current_offset: number | null
  high_watermark: number | null
  lag: number | null
  member_id: string | null
}

export interface GroupDetail {
  group_id: string
  state: GroupState
  is_simple: boolean
  coordinator_id: number | null
  partition_assignor: string | null
  members: GroupMember[]
  lags: PartitionLag[]
  total_lag: number | null
  degraded: Degraded | null
}

export interface ReplicaCell {
  topic: string
  partition: number
  leader: number | null
  replicas: number[]
  in_sync_replicas: number[]
  is_under_replicated: boolean
  is_offline: boolean
  min_insync_replicas: number | null
  at_min_isr: boolean
}

export interface BrokerLoad {
  broker_id: number
  leader_count: number
  replica_count: number
}

export interface ReplicationResponse {
  cells: ReplicaCell[]
  broker_load: BrokerLoad[]
  under_replicated_count: number
  offline_count: number
  at_min_isr_count: number
  non_preferred_leader_count: number
  degraded: Degraded | null
}


// --- M3: messages ---------------------------------------------------------

export type PayloadFormat = 'null' | 'json' | 'avro' | 'protobuf' | 'text' | 'binary'
export type StartFrom = 'newest' | 'oldest' | 'offset' | 'timestamp'
export type StopReason =
  | 'completed' | 'max_results' | 'scanned_budget' | 'time_budget' | 'cancelled' | 'error'

export interface Payload {
  format: PayloadFormat
  value: unknown
  size_bytes: number
  schema_id: number | null
  error: string | null
}

export interface KafkaMessage {
  topic: string
  partition: number
  offset: number
  timestamp: number | null
  timestamp_type: string | null
  key: Payload
  value: Payload
  headers: Record<string, string>
  masked: boolean
}

export interface SearchResponse {
  messages: KafkaMessage[]
  scanned: number
  elapsed_seconds: number
  stop_reason: StopReason
  partitions_scanned: number[]
  format_counts: Record<string, number>
  masking_enabled: boolean
  filter_error: string | null
}

export interface SearchParams {
  topic: string
  partitions?: number[] | null
  start_from?: StartFrom
  offset?: number | null
  timestamp_ms?: number | null
  filter?: string | null
  max_results?: number
  max_scanned?: number
  max_seconds?: number
}


// --- M4: metrics from the built-in sampler --------------------------------

export type LagTrend = 'catching_up' | 'stable' | 'falling_behind' | 'unknown'

export interface SeriesPoint {
  at: string
  value: number | null
}

export interface LagHistory {
  group_id: string
  topic: string | null
  partition: number | null
  lag: SeriesPoint[]
  consume_rate: SeriesPoint[]
  produce_rate: SeriesPoint[]
  trend: LagTrend
  lag_velocity: number | null
  eta_seconds: number | null
  current_lag: number | null
  sampled_points: number
}

export interface ThroughputPoint {
  at: string
  messages_per_second: number
}

export interface TopicThroughput {
  topic: string
  points: ThroughputPoint[]
  average: number | null
  peak: number | null
}

export interface HeatmapCell {
  topic: string
  partition: number
  value: number
}

export interface Heatmap {
  metric: string
  topics: string[]
  max_partition: number
  cells: HeatmapCell[]
  max_value: number
}

export interface SamplerStatus {
  enabled: boolean
  interval_seconds: number
  retention_days: number
  last_run_at: string | null
  last_error: string | null
  prometheus_enabled: boolean
}


// --- M5: admin, audit, users ----------------------------------------------

export type ResetTo = 'earliest' | 'latest' | 'timestamp' | 'offset' | 'shift'
export type AuditResult = 'success' | 'denied' | 'failed'

export interface OffsetChange {
  topic: string
  partition: number
  current_offset: number | null
  target_offset: number
  low_watermark: number | null
  high_watermark: number | null
  messages_skipped: number
  messages_replayed: number
}

export interface OffsetResetResponse {
  group_id: string
  reset_to: ResetTo
  changes: OffsetChange[]
  total_skipped: number
  total_replayed: number
  group_state: string
  member_count: number
  is_safe: boolean
  applied: boolean
  blocked_reason: string | null
}

export interface ConfigChange {
  name: string
  current_value: string | null
  new_value: string | null
  is_default: boolean
}

export interface ConfigDiffResponse {
  topic: string
  changes: ConfigChange[]
  applied: boolean
}

export interface AuditEntry {
  id: number
  at: string
  username: string
  role: Role
  cluster: string | null
  action: string
  target: string | null
  result: AuditResult
  before: string | null
  after: string | null
  detail: string | null
  source_ip: string | null
}

export interface AppUser {
  id: number
  username: string
  role: Role
  provider: string
  email: string | null
  display_name: string | null
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export interface ReplayResponse {
  source_topic: string
  target_topic: string
  matched: number
  copied: number
  scanned: number
  elapsed_seconds: number
  stop_reason: string
  applied: boolean
}


// --- M6: alerts -----------------------------------------------------------

export type AlertKind =
  | 'lag_above' | 'lag_velocity' | 'under_replicated'
  | 'offline_partitions' | 'broker_down' | 'throughput_zero'
export type AlertSeverity = 'info' | 'warning' | 'critical'
export type AlertState = 'ok' | 'firing'

export interface AlertRule {
  id: number
  name: string
  cluster: string
  kind: AlertKind
  severity: AlertSeverity
  enabled: boolean
  topic: string | null
  group_id: string | null
  threshold: number
  for_seconds: number
  cooldown_seconds: number
  notify_webhook: boolean
  notify_slack: boolean
  notify_teams: boolean
  notify_email: string | null
  state: AlertState
  since: string | null
  last_value: number | null
  created_by: string
}

export interface AlertFiring {
  id: number
  rule_id: number
  rule_name: string
  cluster: string
  severity: AlertSeverity
  state: AlertState
  at: string
  value: number | null
  message: string
  acknowledged_at: string | null
  acknowledged_by: string | null
  notified: boolean
  notify_error: string | null
}

export interface AlertKindInfo {
  kind: AlertKind
  label: string
  needs_group: boolean
  needs_topic: boolean
  threshold_hint: string
}


// --- M7: dashboards, flow map, tracer -------------------------------------

export type PanelType = 'throughput' | 'split_by' | 'histogram' | 'top_n' | 'stat'
export type StatOp = 'count' | 'sum' | 'avg' | 'min' | 'max' | 'p95'

export interface PanelSpec {
  id: string
  title: string
  type: PanelType
  topic: string
  partitions?: number[] | null
  extract?: string | null
  filter?: string | null
  window_minutes: number
  max_messages: number
  top_n: number
  buckets: number
  thresholds: number[]
  stat_op: StatOp
  unit?: string | null
  persist: boolean
  retention_days: number
}

export interface PanelBucket {
  label: string
  value: number
}

export interface PanelResult {
  id: string
  title: string
  type: PanelType
  topic: string
  sampled: number
  matched: number
  elapsed_seconds: number
  stop_reason: string
  buckets: PanelBucket[]
  series: { at: number; messages_per_second: number }[]
  stat: number | null
  unit: string | null
  thresholds: number[]
  error: string | null
}

export interface DashboardModel {
  id: number
  name: string
  cluster: string
  description: string | null
  panels: PanelSpec[]
  created_at: string
  updated_at: string
  created_by: string
}

export interface FlowNode {
  id: string
  label: string
  kind: 'topic' | 'group' | 'producer'
  partitions: number | null
  messages_per_second: number | null
  lag: number | null
  state: string | null
}

export interface FlowEdge {
  source: string
  target: string
  kind: string
  origin: 'observed' | 'declared'
  messages_per_second: number | null
  lag: number | null
}

export interface FlowMap {
  nodes: FlowNode[]
  edges: FlowEdge[]
  notes: string[]
  degraded: string | null
}

export interface TraceResult {
  source_topic: string
  target_topic: string
  matched: number
  source_scanned: number
  target_scanned: number
  unmatched_target: number
  p50_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
  min_ms: number | null
  max_ms: number | null
  mean_ms: number | null
  buckets: { label: string; count: number }[]
  negative_count: number
  note: string
}


// --- M8: schemas and ACLs -------------------------------------------------

export type SchemaType = 'AVRO' | 'JSON' | 'PROTOBUF'

export interface SchemaVersion {
  subject: string
  version: number
  id: number
  schema_type: SchemaType
  schema_text: string
  references: Record<string, unknown>[]
}

export interface SubjectSummary {
  name: string
  latest_version: number | null
  versions: number[]
  compatibility: string | null
}

export interface SchemaDiff {
  subject: string
  from_version: number
  to_version: number
  unified: string
  added: number
  removed: number
}

export interface AclModel {
  resource_type: string
  resource_name: string
  pattern_type: string
  principal: string
  host: string
  operation: string
  permission: string
}

export interface AclListResponse {
  acls: AclModel[]
  supported: boolean
  message: string | null
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isUnauthenticated(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }
}

let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

export function getCsrfToken(): string | null {
  return csrfToken
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)

  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (UNSAFE.has(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }

  const response = await fetch(`/api/v1${path}`, {
    ...init,
    method,
    headers,
    // Session cookie is httpOnly; it must ride along on every call.
    credentials: 'same-origin',
  })

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  let parsed: unknown = undefined
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
  }

  if (!response.ok) {
    const detail =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : response.statusText
    throw new ApiError(response.status, detail, parsed)
  }

  return parsed as T
}

export const api = {
  meta: () => request<Meta>('/meta'),
  me: () => request<Me>('/auth/me'),
  login: (username: string, password: string) =>
    request<Me>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  signupAvailability: () =>
    request<{ available: boolean; first_user: boolean; reason: string | null }>('/auth/signup'),

  signup: (username: string, password: string) =>
    request<Me>('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  testCluster: (body: Record<string, unknown>) =>
    request<{ ok: boolean; brokers: number; cluster_id: string | null; topics: number; error: string | null }>(
      '/clusters/test',
      { method: 'POST', body: JSON.stringify(body) },
    ),

  addCluster: (body: Record<string, unknown>) =>
    request<ClusterSummary>('/clusters', { method: 'POST', body: JSON.stringify(body) }),

  removeCluster: (name: string) =>
    request<void>(`/clusters/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  clusters: () => request<{ clusters: ClusterSummary[] }>('/clusters'),

  overview: (cluster: string) =>
    request<ClusterInfo>(`/clusters/${encodeURIComponent(cluster)}/overview`),

  replication: (cluster: string) =>
    request<ReplicationResponse>(`/clusters/${encodeURIComponent(cluster)}/replication`),

  topics: (cluster: string, includeInternal = false) =>
    request<{ topics: TopicSummary[]; degraded: Degraded | null }>(
      `/clusters/${encodeURIComponent(cluster)}/topics?include_internal=${includeInternal}`,
    ),

  topic: (cluster: string, topic: string) =>
    request<TopicDetail>(
      `/clusters/${encodeURIComponent(cluster)}/topics/${encodeURIComponent(topic)}`,
    ),

  topicConfigs: (cluster: string, topic: string) =>
    request<{ topic: string; configs: ConfigEntry[]; degraded: Degraded | null }>(
      `/clusters/${encodeURIComponent(cluster)}/topics/${encodeURIComponent(topic)}/configs`,
    ),

  topicGroups: (cluster: string, topic: string) =>
    request<string[]>(
      `/clusters/${encodeURIComponent(cluster)}/topics/${encodeURIComponent(topic)}/consumer-groups`,
    ),

  groups: (cluster: string, withLag = true) =>
    request<{ groups: GroupSummary[]; degraded: Degraded | null }>(
      `/clusters/${encodeURIComponent(cluster)}/consumer-groups?with_lag=${withLag}`,
    ),

  group: (cluster: string, groupId: string) =>
    request<GroupDetail>(
      `/clusters/${encodeURIComponent(cluster)}/consumer-groups/${encodeURIComponent(groupId)}`,
    ),

  searchMessages: (cluster: string, params: SearchParams, signal?: AbortSignal) =>
    request<SearchResponse>(`/clusters/${encodeURIComponent(cluster)}/messages/search`, {
      method: 'POST',
      body: JSON.stringify(params),
      signal,
    }),

  validateFilter: (cluster: string, filter: string) =>
    request<{ valid: boolean; error: string | null }>(
      `/clusters/${encodeURIComponent(cluster)}/messages/validate-filter`,
      { method: 'POST', body: JSON.stringify({ filter }) },
    ),

  samplerStatus: (cluster: string) =>
    request<SamplerStatus>(`/clusters/${encodeURIComponent(cluster)}/metrics/sampler`),

  lagHistory: (cluster: string, groupId: string, windowMinutes = 60) =>
    request<LagHistory>(
      `/clusters/${encodeURIComponent(cluster)}/metrics/consumer-groups/` +
        `${encodeURIComponent(groupId)}/lag-history?window_minutes=${windowMinutes}`,
    ),

  topicThroughput: (cluster: string, topic: string, windowMinutes = 60) =>
    request<TopicThroughput>(
      `/clusters/${encodeURIComponent(cluster)}/metrics/topics/` +
        `${encodeURIComponent(topic)}/throughput?window_minutes=${windowMinutes}`,
    ),

  heatmap: (cluster: string, metric: 'throughput' | 'lag' = 'throughput', windowMinutes = 30) =>
    request<Heatmap>(
      `/clusters/${encodeURIComponent(cluster)}/metrics/heatmap` +
        `?metric=${metric}&window_minutes=${windowMinutes}`,
    ),

  // --- M5 writes ---
  createTopic: (
    cluster: string,
    body: {
      name: string
      partitions: number
      replication_factor: number
      configs?: Record<string, string>
    },
  ) =>
    request<{ status: string; topic: string }>(
      `/clusters/${encodeURIComponent(cluster)}/topics`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  deleteTopic: (cluster: string, topic: string, confirmName: string) =>
    request<{ status: string }>(
      `/clusters/${encodeURIComponent(cluster)}/topics/${encodeURIComponent(topic)}`,
      { method: 'DELETE', body: JSON.stringify({ confirm_name: confirmName }) },
    ),

  addPartitions: (cluster: string, topic: string, total: number) =>
    request<{ status: string; partitions: number; warning: string }>(
      `/clusters/${encodeURIComponent(cluster)}/topics/${encodeURIComponent(topic)}/partitions`,
      { method: 'POST', body: JSON.stringify({ total_partitions: total }) },
    ),

  alterConfigs: (
    cluster: string,
    topic: string,
    updates: Record<string, string>,
    dryRun = true,
  ) =>
    request<ConfigDiffResponse>(
      `/clusters/${encodeURIComponent(cluster)}/topics/${encodeURIComponent(topic)}/configs`,
      { method: 'POST', body: JSON.stringify({ updates, dry_run: dryRun }) },
    ),

  resetOffsets: (
    cluster: string,
    groupId: string,
    body: {
      reset_to: ResetTo
      topics?: string[] | null
      target_offset?: number | null
      timestamp_ms?: number | null
      shift_by?: number | null
      dry_run: boolean
      confirm_group_id?: string | null
    },
  ) =>
    request<OffsetResetResponse>(
      `/clusters/${encodeURIComponent(cluster)}/consumer-groups/` +
        `${encodeURIComponent(groupId)}/offsets:reset`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  deleteGroup: (cluster: string, groupId: string) =>
    request<{ status: string }>(
      `/clusters/${encodeURIComponent(cluster)}/consumer-groups/${encodeURIComponent(groupId)}`,
      { method: 'DELETE' },
    ),

  produce: (
    cluster: string,
    body: {
      topic: string
      key?: string | null
      value?: string | null
      headers?: Record<string, string>
      partition?: number | null
      confirm_topic: string
    },
  ) =>
    request<{ topic: string; partition: number; offset: number }>(
      `/clusters/${encodeURIComponent(cluster)}/produce`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  replay: (
    cluster: string,
    body: Record<string, unknown>,
  ) =>
    request<ReplayResponse>(`/clusters/${encodeURIComponent(cluster)}/replay`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  electLeaders: (cluster: string) =>
    request<{ status: string; partitions: number }>(
      `/clusters/${encodeURIComponent(cluster)}/elect-leaders`,
      { method: 'POST' },
    ),

  audit: (params: {
    cluster?: string
    action?: string
    username?: string
    result?: AuditResult
    days?: number
    limit?: number
    offset?: number
  }) => {
    const query = new URLSearchParams()
    for (const [name, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') query.set(name, String(value))
    }
    return request<{ entries: AuditEntry[]; total: number }>(`/audit?${query.toString()}`)
  },

  auditActions: () => request<{ actions: string[] }>('/audit/actions'),

  alertRules: () =>
    request<{ rules: AlertRule[]; notifications_configured: boolean }>('/alerts/rules'),

  alertKinds: () => request<AlertKindInfo[]>('/alerts/kinds'),

  createAlertRule: (body: Record<string, unknown>) =>
    request<AlertRule>('/alerts/rules', { method: 'POST', body: JSON.stringify(body) }),

  updateAlertRule: (id: number, body: Record<string, unknown>) =>
    request<AlertRule>(`/alerts/rules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  deleteAlertRule: (id: number) =>
    request<void>(`/alerts/rules/${id}`, { method: 'DELETE' }),

  alertFirings: (days = 7, onlyUnacknowledged = false) =>
    request<{ firings: AlertFiring[]; unacknowledged: number }>(
      `/alerts/firings?days=${days}&only_unacknowledged=${onlyUnacknowledged}`,
    ),

  acknowledgeFiring: (id: number) =>
    request<void>(`/alerts/firings/${id}/acknowledge`, { method: 'POST' }),

  testNotification: () =>
    request<{ results: Record<string, string> }>('/alerts/test-notification', {
      method: 'POST',
    }),

  dashboards: (cluster: string) =>
    request<{ dashboards: DashboardModel[] }>(
      `/clusters/${encodeURIComponent(cluster)}/dashboards`,
    ),

  createDashboard: (
    cluster: string,
    body: { name: string; description?: string | null; panels: PanelSpec[] },
  ) =>
    request<DashboardModel>(`/clusters/${encodeURIComponent(cluster)}/dashboards`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  updateDashboard: (
    cluster: string,
    id: number,
    body: { name: string; description?: string | null; panels: PanelSpec[] },
  ) =>
    request<DashboardModel>(`/clusters/${encodeURIComponent(cluster)}/dashboards/${id}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  deleteDashboard: (cluster: string, id: number) =>
    request<void>(`/clusters/${encodeURIComponent(cluster)}/dashboards/${id}`, {
      method: 'DELETE',
    }),

  renderPanels: (cluster: string, panels: PanelSpec[]) =>
    request<PanelResult[]>(`/clusters/${encodeURIComponent(cluster)}/dashboards/render`, {
      method: 'POST',
      body: JSON.stringify(panels),
    }),

  flowMap: (cluster: string, windowMinutes = 30) =>
    request<FlowMap>(
      `/clusters/${encodeURIComponent(cluster)}/flow-map?window_minutes=${windowMinutes}`,
    ),

  trace: (cluster: string, body: Record<string, unknown>) =>
    request<TraceResult>(`/clusters/${encodeURIComponent(cluster)}/trace`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  subjects: (cluster: string) =>
    request<{ subjects: string[] }>(
      `/clusters/${encodeURIComponent(cluster)}/schemas/subjects`,
    ),

  subject: (cluster: string, subject: string) =>
    request<SubjectSummary>(
      `/clusters/${encodeURIComponent(cluster)}/schemas/subjects/${encodeURIComponent(subject)}`,
    ),

  schemaVersion: (cluster: string, subject: string, version: number | 'latest') =>
    request<SchemaVersion>(
      `/clusters/${encodeURIComponent(cluster)}/schemas/subjects/` +
        `${encodeURIComponent(subject)}/versions/${version}`,
    ),

  schemaDiff: (cluster: string, subject: string, from: number, to: number) =>
    request<SchemaDiff>(
      `/clusters/${encodeURIComponent(cluster)}/schemas/subjects/` +
        `${encodeURIComponent(subject)}/diff?from=${from}&to=${to}`,
    ),

  checkCompatibility: (
    cluster: string,
    subject: string,
    body: { schema_text: string; schema_type: SchemaType },
  ) =>
    request<{ compatible: boolean; messages: string[]; level: string | null }>(
      `/clusters/${encodeURIComponent(cluster)}/schemas/subjects/` +
        `${encodeURIComponent(subject)}/compatibility`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  acls: (cluster: string) =>
    request<AclListResponse>(`/clusters/${encodeURIComponent(cluster)}/acls`),

  aclOptions: (cluster: string) =>
    request<{
      operations: string[]
      permissions: string[]
      resource_types: string[]
      pattern_types: string[]
    }>(`/clusters/${encodeURIComponent(cluster)}/acls/options`),

  createAcl: (cluster: string, body: Record<string, unknown>) =>
    request<{ status: string }>(`/clusters/${encodeURIComponent(cluster)}/acls`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  deleteAcl: (cluster: string, body: Record<string, unknown>) =>
    request<{ status: string; removed: number }>(
      `/clusters/${encodeURIComponent(cluster)}/acls/delete`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  users: () => request<{ users: AppUser[] }>('/users'),

  createUser: (body: {
    username: string
    password: string
    role: Role
    email?: string | null
    display_name?: string | null
  }) => request<AppUser>('/users', { method: 'POST', body: JSON.stringify(body) }),

  updateUser: (username: string, body: { role?: Role; is_active?: boolean }) =>
    request<AppUser>(`/users/${encodeURIComponent(username)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  deleteUser: (username: string) =>
    request<void>(`/users/${encodeURIComponent(username)}`, { method: 'DELETE' }),

  changePassword: (username: string, body: { current_password?: string; new_password: string }) =>
    request<void>(`/users/${encodeURIComponent(username)}/password`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}
