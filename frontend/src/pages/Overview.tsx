import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, type Broker } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { DataTable, type Column } from '@/components/table/DataTable'
import { DegradedBanner, StatusPill } from '@/components/states/StatusPill'
import { EmptyState, Skeleton, TableSkeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'
import { useSession } from '@/lib/session'

function Stat({
  label,
  value,
  tone = 'neutral',
  hint,
}: {
  label: string
  value: string
  tone?: 'ok' | 'warn' | 'critical' | 'neutral'
  hint?: string
}) {
  const colour = {
    ok: 'text-ok',
    warn: 'text-warn',
    critical: 'text-critical',
    neutral: 'text-body',
  }[tone]
  return (
    <div className="rounded-lg border border-subtle bg-surface px-4 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`mt-0.5 text-xl font-semibold tabular ${colour}`}>{value}</dd>
      {hint && <p className="mt-0.5 text-[11px] text-faint">{hint}</p>}
    </div>
  )
}

export function Overview() {
  const { t } = useTranslation()
  const { meta } = useSession()
  const cluster = useClusterName()

  const query = useQuery({
    queryKey: ['overview', cluster],
    queryFn: () => api.overview(cluster!),
    enabled: Boolean(cluster),
  })

  if (!cluster) return <NoCluster />

  const data = query.data

  const brokerColumns: Column<Broker>[] = [
    {
      key: 'id',
      header: t('overview.brokerId'),
      align: 'right',
      sortValue: (row) => row.id,
      render: (row) => (
        <span className="tabular">
          {row.id}
          {row.is_controller && (
            <span className="ml-1.5">
              <StatusPill tone="ok" label={t('overview.controller')} />
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'host',
      header: t('overview.host'),
      sortValue: (row) => row.host,
      render: (row) => (
        <span className="font-mono text-xs">
          {row.host}:{row.port}
        </span>
      ),
    },
    {
      key: 'rack',
      header: t('overview.rack'),
      render: (row) => <span className="text-xs text-muted">{row.rack ?? '—'}</span>,
    },
  ]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold text-body">{t('nav.overview')}</h1>
        <p className="text-xs text-muted">
          {meta.app_name} v{meta.version}
          {data?.cluster_id && (
            <>
              <span aria-hidden="true" className="mx-1.5">
                ·
              </span>
              <span className="font-mono">{data.cluster_id}</span>
            </>
          )}
        </p>
      </div>

      <DegradedBanner degraded={data?.degraded} />

      {query.isPending ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-[76px]" />
            ))}
          </div>
          <TableSkeleton rows={3} />
        </>
      ) : query.isError ? (
        <EmptyState
          icon="▲"
          title={t('errors.genericTitle')}
          body={t('errors.genericBody')}
          action={
            <button
              type="button"
              onClick={() => void query.refetch()}
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover"
            >
              {t('common.retry')}
            </button>
          }
        />
      ) : (
        <>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <Stat label={t('overview.brokers')} value={formatNumber(data?.brokers.length ?? 0)} />
            <Stat label={t('nav.topics')} value={formatNumber(data?.topic_count ?? 0)} />
            <Stat
              label={t('overview.partitions')}
              value={formatNumber(data?.partition_count ?? 0)}
              hint={
                data?.internal_partition_count
                  ? t('overview.internalPartitions', {
                      count: data.internal_partition_count,
                    })
                  : undefined
              }
            />
            <Stat
              label={t('overview.underReplicated')}
              value={formatNumber(data?.under_replicated_partitions ?? 0)}
              tone={data?.under_replicated_partitions ? 'warn' : 'ok'}
            />
            <Stat
              label={t('overview.offline')}
              value={formatNumber(data?.offline_partitions ?? 0)}
              tone={data?.offline_partitions ? 'critical' : 'ok'}
            />
            <Stat
              label={t('overview.mode')}
              value={(data?.mode ?? 'unknown').toUpperCase()}
              hint={
                data?.controller_id !== null && data?.controller_id !== undefined
                  ? t('overview.controllerIs', { id: data.controller_id })
                  : undefined
              }
            />
          </dl>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-body">{t('overview.brokers')}</h2>
            <DataTable
              rows={data?.brokers ?? []}
              columns={brokerColumns}
              getRowKey={(row) => String(row.id)}
              initialSortKey="id"
              emptyState={<EmptyState title={t('overview.noBrokers')} />}
            />
          </section>

          {data && data.capabilities.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-body">{t('overview.capabilities')}</h2>
              <p className="text-xs text-muted">{t('overview.capabilitiesHint')}</p>
              <ul className="flex flex-wrap gap-1.5">
                {data.capabilities.map((capability) => (
                  <li key={capability}>
                    <span className="rounded border border-subtle bg-surface px-1.5 py-0.5 font-mono text-[11px] text-muted">
                      {capability}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}
