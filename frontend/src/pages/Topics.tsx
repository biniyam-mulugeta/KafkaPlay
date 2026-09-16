import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, type TopicSummary } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { DataTable, type Column } from '@/components/table/DataTable'
import { DegradedBanner, StatusPill } from '@/components/states/StatusPill'
import { EmptyState, TableSkeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'

export function Topics() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const [search, setSearch] = useState('')
  const [includeInternal, setIncludeInternal] = useState(false)

  const query = useQuery({
    queryKey: ['topics', cluster, includeInternal],
    queryFn: () => api.topics(cluster!, includeInternal),
    enabled: Boolean(cluster),
  })

  const filtered = useMemo(() => {
    const topics = query.data?.topics ?? []
    const needle = search.trim().toLowerCase()
    return needle ? topics.filter((topic) => topic.name.toLowerCase().includes(needle)) : topics
  }, [query.data, search])

  const columns: Column<TopicSummary>[] = [
    {
      key: 'name',
      header: t('topics.name'),
      sortValue: (row) => row.name,
      render: (row) => (
        <Link
          to={`/topics/${encodeURIComponent(row.name)}`}
          className="font-medium text-brand hover:underline"
        >
          {row.name}
        </Link>
      ),
    },
    {
      key: 'partitions',
      header: t('topics.partitions'),
      align: 'right',
      sortValue: (row) => row.partition_count,
      render: (row) => <span className="tabular">{formatNumber(row.partition_count)}</span>,
    },
    {
      key: 'replication',
      header: t('topics.replication'),
      align: 'right',
      sortValue: (row) => row.replication_factor,
      render: (row) => (
        <span className="tabular">
          {row.replication_factor}
          {/* RF=1 means one broker failure loses the data. Worth flagging. */}
          {row.replication_factor === 1 && (
            <span className="ml-1.5">
              <StatusPill tone="warn" label="RF 1" title={t('topics.rfOneHint')} />
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'health',
      header: t('topics.health'),
      sortValue: (row) => row.offline_partitions * 10 + row.under_replicated_partitions,
      render: (row) => {
        if (row.offline_partitions > 0) {
          return (
            <StatusPill
              tone="critical"
              label={t('topics.offlineCount', { count: row.offline_partitions })}
            />
          )
        }
        if (row.under_replicated_partitions > 0) {
          return (
            <StatusPill
              tone="warn"
              label={t('topics.underReplicatedCount', { count: row.under_replicated_partitions })}
            />
          )
        }
        return <StatusPill tone="ok" label={t('topics.healthy')} />
      },
    },
  ]

  if (!cluster) return <NoCluster />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-body">{t('nav.topics')}</h1>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={includeInternal}
            onChange={(event) => setIncludeInternal(event.target.checked)}
          />
          {t('topics.showInternal')}
        </label>
      </div>

      <DegradedBanner degraded={query.data?.degraded} />

      {query.isPending ? (
        <TableSkeleton rows={8} />
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
        <DataTable
          rows={filtered}
          columns={columns}
          getRowKey={(row) => row.name}
          initialSortKey="name"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder={t('topics.searchPlaceholder')}
          emptyState={
            <EmptyState
              title={search ? t('topics.noMatches') : t('topics.none')}
              body={search ? t('topics.noMatchesHelp') : t('topics.noneHelp')}
            />
          }
        />
      )}
    </div>
  )
}
