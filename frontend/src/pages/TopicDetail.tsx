import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, type ConfigEntry, type PartitionInfo } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { DataTable, type Column } from '@/components/table/DataTable'
import { DegradedBanner, StatusPill } from '@/components/states/StatusPill'
import { EmptyState, Skeleton, TableSkeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'

type Tab = 'partitions' | 'configs' | 'groups'

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-subtle bg-surface px-4 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold text-body tabular">{value}</dd>
    </div>
  )
}

export function TopicDetail() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const { topic = '' } = useParams()
  const [tab, setTab] = useState<Tab>('partitions')

  const detail = useQuery({
    queryKey: ['topic', cluster, topic],
    queryFn: () => api.topic(cluster!, topic),
    enabled: Boolean(cluster && topic),
  })

  const configs = useQuery({
    queryKey: ['topic-configs', cluster, topic],
    queryFn: () => api.topicConfigs(cluster!, topic),
    // Only fetched when the tab is opened, to keep the page cheap.
    enabled: Boolean(cluster && topic) && tab === 'configs',
    refetchInterval: false,
  })

  const groups = useQuery({
    queryKey: ['topic-groups', cluster, topic],
    queryFn: () => api.topicGroups(cluster!, topic),
    // Expensive: one describe per consumer group on the cluster.
    enabled: Boolean(cluster && topic) && tab === 'groups',
    refetchInterval: false,
  })

  if (!cluster) return <NoCluster />

  const partitionColumns: Column<PartitionInfo>[] = [
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
      sortValue: (row) => row.leader,
      render: (row) =>
        row.leader === null ? (
          <StatusPill tone="critical" label={t('topicDetail.offline')} />
        ) : (
          <span className="tabular">{row.leader}</span>
        ),
    },
    {
      key: 'replicas',
      header: t('topicDetail.replicas'),
      render: (row) => <span className="tabular text-muted">{row.replicas.join(', ')}</span>,
    },
    {
      key: 'isr',
      header: t('topicDetail.isr'),
      render: (row) => (
        <span className="tabular">
          {row.in_sync_replicas.join(', ')}
          {row.in_sync_replicas.length < row.replicas.length && (
            <span className="ml-1.5">
              <StatusPill tone="warn" label={t('topicDetail.underReplicated')} />
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'low',
      header: t('topicDetail.lowWatermark'),
      align: 'right',
      sortValue: (row) => row.low_watermark,
      render: (row) => (
        <span className="tabular text-muted">
          {row.low_watermark === null ? '—' : formatNumber(row.low_watermark)}
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
      key: 'messages',
      header: t('topicDetail.messages'),
      align: 'right',
      sortValue: (row) =>
        row.high_watermark !== null && row.low_watermark !== null
          ? row.high_watermark - row.low_watermark
          : null,
      render: (row) => {
        if (row.high_watermark === null || row.low_watermark === null) {
          return <span className="text-faint">—</span>
        }
        return (
          <span className="tabular">
            {formatNumber(Math.max(0, row.high_watermark - row.low_watermark))}
          </span>
        )
      },
    },
  ]

  const configColumns: Column<ConfigEntry>[] = [
    {
      key: 'name',
      header: t('topicDetail.configName'),
      sortValue: (row) => row.name,
      render: (row) => <span className="font-mono text-xs">{row.name}</span>,
    },
    {
      key: 'value',
      header: t('topicDetail.configValue'),
      render: (row) => (
        <span className="font-mono text-xs">
          {row.is_sensitive ? '••••••' : (row.value ?? '—')}
        </span>
      ),
    },
    {
      key: 'source',
      header: t('topicDetail.configSource'),
      sortValue: (row) => (row.is_default ? 1 : 0),
      render: (row) =>
        row.is_default ? (
          <span className="text-xs text-faint">{t('topicDetail.default')}</span>
        ) : (
          // A non-default value was set deliberately; make it obvious.
          <StatusPill tone="warn" label={t('topicDetail.overridden')} />
        ),
    },
  ]

  return (
    <div className="space-y-5">
      <div>
        <nav aria-label="Breadcrumb" className="mb-1 text-xs text-muted">
          <Link to="/topics" className="hover:text-body hover:underline">
            {t('nav.topics')}
          </Link>
          <span aria-hidden="true" className="mx-1.5">
            /
          </span>
          <span className="text-body">{topic}</span>
        </nav>
        <h1 className="font-mono text-lg font-semibold text-body">{topic}</h1>
      </div>

      <DegradedBanner degraded={detail.data?.degraded} />

      {detail.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-[72px]" />
          ))}
        </div>
      ) : detail.isError ? (
        <EmptyState icon="▲" title={t('topicDetail.notFound')} body={t('topicDetail.notFoundHelp')} />
      ) : (
        <>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label={t('topics.partitions')}
              value={formatNumber(detail.data.partitions.length)}
            />
            <Stat
              label={t('topics.replication')}
              value={String(detail.data.replication_factor)}
            />
            <Stat
              label={t('topicDetail.messages')}
              value={
                detail.data.message_count === null
                  ? '—'
                  : formatNumber(detail.data.message_count)
              }
            />
            <Stat
              label={t('topicDetail.internal')}
              value={detail.data.is_internal ? t('common.yes') : t('common.no')}
            />
          </dl>

          <div role="tablist" className="flex gap-1 border-b border-subtle">
            {(['partitions', 'configs', 'groups'] as Tab[]).map((name) => (
              <button
                key={name}
                role="tab"
                aria-selected={tab === name}
                onClick={() => setTab(name)}
                className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
                  tab === name
                    ? 'border-brand font-medium text-brand'
                    : 'border-transparent text-muted hover:text-body'
                }`}
              >
                {t(`topicDetail.tab.${name}`)}
              </button>
            ))}
          </div>

          {tab === 'partitions' && (
            <DataTable
              rows={detail.data.partitions}
              columns={partitionColumns}
              getRowKey={(row) => String(row.partition)}
              initialSortKey="partition"
            />
          )}

          {tab === 'configs' &&
            (configs.isPending ? (
              <TableSkeleton rows={8} />
            ) : (
              <>
                <DegradedBanner degraded={configs.data?.degraded} />
                <DataTable
                  rows={configs.data?.configs ?? []}
                  columns={configColumns}
                  getRowKey={(row) => row.name}
                  initialSortKey="name"
                  emptyState={<EmptyState title={t('topicDetail.noConfigs')} />}
                />
              </>
            ))}

          {tab === 'groups' &&
            (groups.isPending ? (
              <TableSkeleton rows={3} />
            ) : (groups.data ?? []).length === 0 ? (
              <EmptyState title={t('topicDetail.noGroups')} body={t('topicDetail.noGroupsHelp')} />
            ) : (
              <ul className="space-y-1">
                {(groups.data ?? []).map((group) => (
                  <li key={group}>
                    <Link
                      to={`/consumer-groups/${encodeURIComponent(group)}`}
                      className="text-sm text-brand hover:underline"
                    >
                      {group}
                    </Link>
                  </li>
                ))}
              </ul>
            ))}
        </>
      )}
    </div>
  )
}
