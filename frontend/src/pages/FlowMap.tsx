import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, api, type FlowNode, type TraceResult } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { Banner } from '@/components/states/Banner'
import { EmptyState, Skeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'
import { StatusPill } from '@/components/states/StatusPill'
import { useSession } from '@/lib/session'

function NodeCard({ node }: { node: FlowNode }) {
  const { t } = useTranslation()
  const tone =
    node.kind === 'topic' ? 'border-brand' : node.kind === 'group' ? 'border-info' : 'border-strong'

  return (
    <div className={`rounded border-l-4 bg-surface px-3 py-2 ${tone}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate font-mono text-xs text-body">{node.label}</span>
        <span className="text-[10px] uppercase text-faint">{t(`flow.kind.${node.kind}`)}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-2 text-[11px] text-muted">
        {node.partitions !== null && (
          <span className="tabular">
            {node.partitions} {t('topics.partitions').toLowerCase()}
          </span>
        )}
        {node.messages_per_second !== null && (
          <span className="tabular">{node.messages_per_second.toFixed(2)} msg/s</span>
        )}
        {node.lag !== null && (
          <span className="tabular">
            {t('groups.lag')} {formatNumber(node.lag)}
          </span>
        )}
        {node.state && <span>{node.state}</span>}
      </div>
    </div>
  )
}

function Tracer() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const { me, meta } = useSession()
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const [sourceKey, setSourceKey] = useState('value.id')
  const [targetKey, setTargetKey] = useState('value.id')
  const [result, setResult] = useState<TraceResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const topics = useQuery({
    queryKey: ['topics', cluster, false],
    queryFn: () => api.topics(cluster!, false),
    enabled: Boolean(cluster),
    refetchInterval: false,
  })

  const trace = useMutation({
    mutationFn: () =>
      api.trace(cluster!, {
        source_topic: source,
        target_topic: target,
        source_key: sourceKey,
        target_key: targetKey,
        timestamp_source: 'kafka',
      }),
    onSuccess: (data) => {
      setResult(data)
      setError(null)
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  const canTrace = !meta.read_only || me?.role === 'operator' || me?.role === 'admin'

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-body">{t('flow.tracerTitle')}</h2>
        <p className="mt-0.5 text-xs text-muted">{t('flow.tracerSubtitle')}</p>
      </div>

      {error && <Banner tone="critical" title={t('errors.genericTitle')}>{error}</Banner>}

      <div className="flex flex-wrap items-end gap-2 rounded-lg border border-subtle bg-surface p-3">
        <div>
          <label htmlFor="trace-source" className="block text-[11px] font-medium text-muted">
            {t('flow.sourceTopic')}
          </label>
          <select
            id="trace-source"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            className="mt-1 rounded border border-subtle bg-surface px-2 py-1 text-xs"
          >
            <option value="">{t('messages.selectTopic')}</option>
            {(topics.data?.topics ?? []).map((topic) => (
              <option key={topic.name} value={topic.name}>
                {topic.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="trace-source-key" className="block text-[11px] font-medium text-muted">
            {t('flow.sourceKey')}
          </label>
          <input
            id="trace-source-key"
            value={sourceKey}
            onChange={(event) => setSourceKey(event.target.value)}
            className="mt-1 w-36 rounded border border-subtle bg-surface px-2 py-1 font-mono text-xs"
          />
        </div>
        <span aria-hidden="true" className="pb-1.5 text-muted">
          →
        </span>
        <div>
          <label htmlFor="trace-target" className="block text-[11px] font-medium text-muted">
            {t('flow.targetTopic')}
          </label>
          <select
            id="trace-target"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            className="mt-1 rounded border border-subtle bg-surface px-2 py-1 text-xs"
          >
            <option value="">{t('messages.selectTopic')}</option>
            {(topics.data?.topics ?? []).map((topic) => (
              <option key={topic.name} value={topic.name}>
                {topic.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="trace-target-key" className="block text-[11px] font-medium text-muted">
            {t('flow.targetKey')}
          </label>
          <input
            id="trace-target-key"
            value={targetKey}
            onChange={(event) => setTargetKey(event.target.value)}
            className="mt-1 w-36 rounded border border-subtle bg-surface px-2 py-1 font-mono text-xs"
          />
        </div>
        <button
          type="button"
          disabled={!source || !target || trace.isPending || !canTrace}
          onClick={() => trace.mutate()}
          className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-50"
        >
          {trace.isPending ? t('flow.tracing') : t('flow.runTrace')}
        </button>
      </div>

      {result && (
        <div className="space-y-2 rounded-lg border border-subtle bg-surface p-4">
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {(
              [
                ['p50', result.p50_ms],
                ['p95', result.p95_ms],
                ['p99', result.p99_ms],
                ['min', result.min_ms],
                ['max', result.max_ms],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <div className="text-[11px] text-muted">{label}</div>
                <div className="tabular text-lg font-semibold text-body">
                  {value === null ? '—' : `${formatNumber(Math.round(value))} ms`}
                </div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-2 text-[11px] text-muted">
            <span>{t('flow.matched', { count: result.matched })}</span>
            {result.unmatched_target > 0 && (
              <StatusPill
                tone="warn"
                label={t('flow.unmatched', { count: result.unmatched_target })}
                title={t('flow.unmatchedHint')}
              />
            )}
            {result.negative_count > 0 && (
              <StatusPill
                tone="warn"
                label={t('flow.negative', { count: result.negative_count })}
                title={t('flow.negativeHint')}
              />
            )}
          </div>

          {result.buckets.length > 0 && (
            <ul className="space-y-1">
              {result.buckets.map((bucket) => {
                const max = Math.max(...result.buckets.map((item) => item.count))
                return (
                  <li key={bucket.label} className="flex items-center gap-2 text-[11px]">
                    <span className="w-20 text-right text-muted">{bucket.label}</span>
                    <span
                      className="h-3 rounded-sm bg-brand"
                      style={{ width: `${Math.max(2, (bucket.count / max) * 100)}%` }}
                    />
                    <span className="tabular text-faint">{bucket.count}</span>
                  </li>
                )
              })}
            </ul>
          )}

          <p className="text-[11px] text-faint">{result.note}</p>
        </div>
      )}
    </section>
  )
}

export function FlowMapPage() {
  const { t } = useTranslation()
  const cluster = useClusterName()

  const flow = useQuery({
    queryKey: ['flow-map', cluster],
    queryFn: () => api.flowMap(cluster!, 30),
    enabled: Boolean(cluster),
    refetchInterval: 30_000,
  })

  if (!cluster) return <NoCluster />

  const nodes = flow.data?.nodes ?? []
  const byKind = {
    producer: nodes.filter((node) => node.kind === 'producer'),
    topic: nodes.filter((node) => node.kind === 'topic'),
    group: nodes.filter((node) => node.kind === 'group'),
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-body">{t('nav.flowMap')}</h1>
        <p className="mt-1 text-sm text-muted">{t('flow.subtitle')}</p>
      </div>

      {flow.data?.degraded && (
        <Banner tone="warn" title={t('errors.genericTitle')}>{flow.data.degraded}</Banner>
      )}

      {(flow.data?.notes ?? []).map((note) => (
        <Banner key={note} tone="info" title={t('flow.limitation')}>
          {note}
        </Banner>
      ))}

      {flow.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : nodes.length === 0 ? (
        <EmptyState title={t('flow.empty')} body={t('flow.emptyHelp')} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          {(['producer', 'topic', 'group'] as const).map((kind) => (
            <section key={kind} className="space-y-2">
              <h2 className="text-sm font-semibold text-body">
                {t(`flow.column.${kind}`)}
                <span className="ml-1.5 text-xs font-normal text-faint">
                  {byKind[kind].length}
                </span>
              </h2>
              {byKind[kind].length === 0 ? (
                <p className="rounded border border-dashed border-strong px-3 py-4 text-center text-[11px] text-muted">
                  {kind === 'producer' ? t('flow.noProducers') : t('flow.noneInColumn')}
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {byKind[kind].map((node) => (
                    <li key={node.id}>
                      <NodeCard node={node} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}

      {(flow.data?.edges ?? []).length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-body">{t('flow.edges')}</h2>
          <ul className="space-y-1 rounded-lg border border-subtle bg-surface p-3">
            {(flow.data?.edges ?? []).map((edge, index) => (
              <li
                key={`${edge.source}-${edge.target}-${index}`}
                className="flex flex-wrap items-center gap-2 text-xs"
              >
                <span className="font-mono text-muted">{edge.source.split(':')[1]}</span>
                <span aria-hidden="true" className="text-faint">
                  →
                </span>
                <span className="font-mono text-muted">{edge.target.split(':')[1]}</span>
                <span className="text-[10px] text-faint">{edge.kind}</span>
                <StatusPill
                  tone={edge.origin === 'observed' ? 'ok' : 'neutral'}
                  label={t(`flow.origin.${edge.origin}`)}
                  title={
                    edge.origin === 'observed'
                      ? t('flow.observedHint')
                      : t('flow.declaredHint')
                  }
                />
                {edge.lag !== null && edge.lag > 0 && (
                  <span className="tabular text-[11px] text-warn">
                    {t('groups.lag')} {formatNumber(edge.lag)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <Tracer />
    </div>
  )
}
