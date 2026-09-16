import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, type BrokerLoad, type ReplicaCell } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { DataTable, type Column } from '@/components/table/DataTable'
import { DegradedBanner, StatusPill } from '@/components/states/StatusPill'
import { EmptyState, Skeleton, TableSkeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: number
  tone?: 'ok' | 'warn' | 'critical' | 'neutral'
}) {
  // Zero is the healthy answer for every counter on this page, so colour only
  // appears when there is something to act on.
  const effective = value === 0 ? 'ok' : tone
  const colour = {
    ok: 'text-ok',
    warn: 'text-warn',
    critical: 'text-critical',
    neutral: 'text-body',
  }[effective]
  return (
    <div className="rounded-lg border border-subtle bg-surface px-4 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`mt-0.5 text-lg font-semibold tabular ${colour}`}>{formatNumber(value)}</dd>
    </div>
  )
}

export function Replication() {
  const { t } = useTranslation()
  const cluster = useClusterName()

  const query = useQuery({
    queryKey: ['replication', cluster],
    queryFn: () => api.replication(cluster!),
    enabled: Boolean(cluster),
    // Heavier than other reads: one describe per topic.
    refetchInterval: 30_000,
  })

  if (!cluster) return <NoCluster />

  const problemCells = (query.data?.cells ?? []).filter(
    (cell) => cell.is_offline || cell.is_under_replicated || cell.at_min_isr,
  )

  const cellColumns: Column<ReplicaCell>[] = [
    {
      key: 'topic',
      header: t('groups.topic'),
      sortValue: (row) => row.topic,
      render: (row) => <span className="font-mono text-xs">{row.topic}</span>,
    },
    {
      key: 'partition',
      header: t('topicDetail.partition'),
      align: 'right',
      sortValue: (row) => row.partition,
      render: (row) => <span className="tabular">{row.partition}</span>,
    },
    {
      key: 'leader',
      header: t('topicDetail.leader'),
      align: 'right',
      render: (row) => <span className="tabular">{row.leader ?? '—'}</span>,
    },
    {
      key: 'isr',
      header: t('replication.isrOfReplicas'),
      render: (row) => (
        <span className="tabular">
          {row.in_sync_replicas.length} / {row.replicas.length}
          {row.min_insync_replicas !== null && (
            <span className="ml-1 text-xs text-faint">
              (min {row.min_insync_replicas})
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'status',
      header: t('topics.health'),
      render: (row) => {
        if (row.is_offline) {
          return <StatusPill tone="critical" label={t('replication.offline')} />
        }
        if (row.is_under_replicated) {
          return <StatusPill tone="warn" label={t('topicDetail.underReplicated')} />
        }
        if (row.at_min_isr) {
          return (
            <StatusPill
              tone="warn"
              label={t('replication.atMinIsr')}
              title={t('replication.atMinIsrHint')}
            />
          )
        }
        return <StatusPill tone="ok" label={t('topics.healthy')} />
      },
    },
  ]

  const loadColumns: Column<BrokerLoad>[] = [
    {
      key: 'broker',
      header: t('replication.broker'),
      align: 'right',
      sortValue: (row) => row.broker_id,
      render: (row) => <span className="tabular">{row.broker_id}</span>,
    },
    {
      key: 'leaders',
      header: t('replication.leaders'),
      align: 'right',
      sortValue: (row) => row.leader_count,
      render: (row) => <span className="tabular">{formatNumber(row.leader_count)}</span>,
    },
    {
      key: 'replicas',
      header: t('replication.replicas'),
      align: 'right',
      sortValue: (row) => row.replica_count,
      render: (row) => <span className="tabular">{formatNumber(row.replica_count)}</span>,
    },
  ]

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-body">{t('nav.replication')}</h1>
        <p className="mt-1 text-sm text-muted">{t('replication.subtitle')}</p>
      </div>

      <DegradedBanner degraded={query.data?.degraded} />

      {query.isPending ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-[72px]" />
            ))}
          </div>
          <TableSkeleton rows={6} />
        </>
      ) : (
        <>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label={t('replication.offlinePartitions')}
              value={query.data?.offline_count ?? 0}
              tone="critical"
            />
            <Stat
              label={t('replication.underReplicated')}
              value={query.data?.under_replicated_count ?? 0}
              tone="warn"
            />
            <Stat
              label={t('replication.atMinIsr')}
              value={query.data?.at_min_isr_count ?? 0}
              tone="warn"
            />
            <Stat
              label={t('replication.nonPreferredLeaders')}
              value={query.data?.non_preferred_leader_count ?? 0}
              tone="warn"
            />
          </dl>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-body">{t('replication.brokerBalance')}</h2>
            <p className="text-xs text-muted">{t('replication.brokerBalanceHint')}</p>
            <DataTable
              rows={query.data?.broker_load ?? []}
              columns={loadColumns}
              getRowKey={(row) => String(row.broker_id)}
              initialSortKey="broker"
              emptyState={<EmptyState title={t('replication.noBrokers')} />}
            />
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-body">
              {t('replication.partitionsNeedingAttention')}
            </h2>
            <DataTable
              rows={problemCells}
              columns={cellColumns}
              getRowKey={(row) => `${row.topic}-${row.partition}`}
              emptyState={
                <EmptyState
                  icon="✓"
                  title={t('replication.allHealthy')}
                  body={t('replication.allHealthyHelp')}
                />
              }
            />
          </section>
        </>
      )}
    </div>
  )
}
