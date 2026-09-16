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
}
