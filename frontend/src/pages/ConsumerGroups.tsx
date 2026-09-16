import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, type GroupSummary } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { DataTable, type Column } from '@/components/table/DataTable'
import { DegradedBanner, GroupStatePill, StatusPill } from '@/components/states/StatusPill'
import { EmptyState, TableSkeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'

/** Lag thresholds are advisory only; the alert rules in M6 are configurable. */
const LAG_WARN = 1_000
const LAG_CRITICAL = 100_000

export function LagCell({ lag }: { lag: number | null }) {
  const { t } = useTranslation()
  if (lag === null) {
    return <span className="text-faint">{t('groups.noCommits')}</span>
  }
  const tone = lag >= LAG_CRITICAL ? 'critical' : lag >= LAG_WARN ? 'warn' : 'ok'
  return <StatusPill tone={tone} label={formatNumber(lag)} />
}

export function ConsumerGroups() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const [search, setSearch] = useState('')

  const query = useQuery({
    queryKey: ['groups', cluster],
    queryFn: () => api.groups(cluster!, true),
    enabled: Boolean(cluster),
  })

  const filtered = useMemo(() => {
    const groups = query.data?.groups ?? []
    const needle = search.trim().toLowerCase()
    return needle
      ? groups.filter(
          (group) =>
            group.group_id.toLowerCase().includes(needle) ||
            group.topics.some((topic) => topic.toLowerCase().includes(needle)),
        )
      : groups
  }, [query.data, search])

  const columns: Column<GroupSummary>[] = [
    {
      key: 'group',
      header: t('groups.groupId'),
      sortValue: (row) => row.group_id,
      render: (row) => (
        <Link
          to={`/consumer-groups/${encodeURIComponent(row.group_id)}`}
          className="font-medium text-brand hover:underline"
        >
          {row.group_id}
        </Link>
      ),
    },
    {
      key: 'state',
      header: t('groups.state'),
      sortValue: (row) => row.state,
      render: (row) => <GroupStatePill state={row.state} />,
    },
    {
      key: 'topics',
      header: t('groups.topics'),
      render: (row) =>
        row.topics.length === 0 ? (
          <span className="text-faint">—</span>
        ) : (
          <span className="text-xs text-muted">{row.topics.join(', ')}</span>
        ),
    },
    {
      key: 'lag',
      header: t('groups.totalLag'),
      align: 'right',
      sortValue: (row) => row.total_lag,
      render: (row) => <LagCell lag={row.total_lag} />,
    },
  ]

  if (!cluster) return <NoCluster />

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-body">{t('nav.consumerGroups')}</h1>

      <DegradedBanner degraded={query.data?.degraded} />

      {query.isPending ? (
        <TableSkeleton rows={6} />
      ) : (
        <DataTable
          rows={filtered}
          columns={columns}
          getRowKey={(row) => row.group_id}
          initialSortKey="group"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder={t('groups.searchPlaceholder')}
          emptyState={<EmptyState title={t('groups.none')} body={t('groups.noneHelp')} />}
        />
      )}
    </div>
  )
}
