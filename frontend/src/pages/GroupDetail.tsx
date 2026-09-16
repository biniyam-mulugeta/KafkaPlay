import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, type GroupMember, type PartitionLag } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { DataTable, type Column } from '@/components/table/DataTable'
import { DegradedBanner, GroupStatePill } from '@/components/states/StatusPill'
import { EmptyState, Skeleton } from '@/components/states/EmptyState'
import { LagCell } from '@/pages/ConsumerGroups'
import { NoCluster } from '@/components/states/NoCluster'

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-subtle bg-surface px-4 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold text-body">{value}</dd>
    </div>
  )
}

export function GroupDetail() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const { groupId = '' } = useParams()

  const query = useQuery({
    queryKey: ['group', cluster, groupId],
    queryFn: () => api.group(cluster!, groupId),
    enabled: Boolean(cluster && groupId),
  })

  if (!cluster) return <NoCluster />

  const lagColumns: Column<PartitionLag>[] = [
    {
      key: 'topic',
      header: t('groups.topic'),
      sortValue: (row) => row.topic,
      render: (row) => (
        <Link
          to={`/topics/${encodeURIComponent(row.topic)}`}
          className="font-mono text-xs text-brand hover:underline"
        >
          {row.topic}
        </Link>
      ),
    },
    {
      key: 'partition',
      header: t('topicDetail.partition'),
      align: 'right',
      sortValue: (row) => row.partition,
      render: (row) => <span className="tabular">{row.partition}</span>,
    },
    {
      key: 'committed',
      header: t('groups.committedOffset'),
      align: 'right',
      sortValue: (row) => row.current_offset,
      render: (row) => (
        <span className="tabular text-muted">
          {row.current_offset === null ? '—' : formatNumber(row.current_offset)}
        </span>
      ),
    },
    {
      key: 'high',
      header: t('topicDetail.highWatermark'),
      align: 'right',
      sortValue: (row) => row.high_watermark,
      render: (row) => (
        <span className="tabular">
          {row.high_watermark === null ? '—' : formatNumber(row.high_watermark)}
        </span>
      ),
    },
    {
      key: 'lag',
      header: t('groups.lag'),
      align: 'right',
      sortValue: (row) => row.lag,
      render: (row) => <LagCell lag={row.lag} />,
    },
  ]

  const memberColumns: Column<GroupMember>[] = [
    {
      key: 'member',
      header: t('groups.member'),
      sortValue: (row) => row.member_id,
      render: (row) => <span className="font-mono text-xs">{row.member_id}</span>,
    },
    {
      key: 'client',
      header: t('groups.clientId'),
      render: (row) => <span className="text-xs text-muted">{row.client_id ?? '—'}</span>,
    },
    {
      key: 'host',
      header: t('groups.host'),
      render: (row) => <span className="font-mono text-xs text-muted">{row.host ?? '—'}</span>,
    },
    {
      key: 'assignments',
      header: t('groups.assignments'),
      render: (row) =>
        row.assignments.length === 0 ? (
          <span className="text-faint">—</span>
        ) : (
          <span className="text-xs text-muted">
            {row.assignments
              .map((a) => `${a.topic} [${a.partitions.join(', ')}]`)
              .join('; ')}
          </span>
        ),
    },
  ]

  return (
    <div className="space-y-5">
      <div>
        <nav aria-label="Breadcrumb" className="mb-1 text-xs text-muted">
          <Link to="/consumer-groups" className="hover:text-body hover:underline">
            {t('nav.consumerGroups')}
          </Link>
          <span aria-hidden="true" className="mx-1.5">
            /
          </span>
          <span className="text-body">{groupId}</span>
        </nav>
        <h1 className="font-mono text-lg font-semibold text-body">{groupId}</h1>
      </div>

      <DegradedBanner degraded={query.data?.degraded} />

      {query.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-[72px]" />
          ))}
        </div>
      ) : query.isError ? (
        <EmptyState icon="▲" title={t('errors.genericTitle')} body={t('errors.genericBody')} />
      ) : (
        <>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={t('groups.state')} value={<GroupStatePill state={query.data.state} />} />
            <Stat
              label={t('groups.members')}
              value={<span className="tabular">{query.data.members.length}</span>}
            />
            <Stat label={t('groups.totalLag')} value={<LagCell lag={query.data.total_lag} />} />
            <Stat
              label={t('groups.assignor')}
              value={
                <span className="text-sm text-muted">
                  {query.data.partition_assignor || '—'}
                </span>
              }
            />
          </dl>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-body">{t('groups.lagByPartition')}</h2>
            <DataTable
              rows={query.data.lags}
              columns={lagColumns}
              getRowKey={(row) => `${row.topic}-${row.partition}`}
              initialSortKey="lag"
              emptyState={
                <EmptyState title={t('groups.noOffsets')} body={t('groups.noOffsetsHelp')} />
              }
            />
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-body">{t('groups.members')}</h2>
            <DataTable
              rows={query.data.members}
              columns={memberColumns}
              getRowKey={(row) => row.member_id}
              emptyState={
                // An empty group is normal when consumers are stopped, and is
                // also the precondition for a safe offset reset in M5.
                <EmptyState title={t('groups.noMembers')} body={t('groups.noMembersHelp')} />
              }
            />
          </section>
        </>
      )}
    </div>
  )
}
