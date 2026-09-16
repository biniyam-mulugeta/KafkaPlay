import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatRelative } from '@/lib/format'
import { Banner } from '@/components/states/Banner'
import { EmptyState, Skeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'
import { PartitionHeatmap } from '@/components/charts/HeatmapChart'

const WINDOWS = [15, 30, 60, 180, 720]

export function Metrics() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const [metric, setMetric] = useState<'throughput' | 'lag'>('throughput')
  const [windowMinutes, setWindowMinutes] = useState(30)

  const status = useQuery({
    queryKey: ['sampler', cluster],
    queryFn: () => api.samplerStatus(cluster!),
    enabled: Boolean(cluster),
    refetchInterval: 15_000,
  })

  const heatmap = useQuery({
    queryKey: ['heatmap', cluster, metric, windowMinutes],
    queryFn: () => api.heatmap(cluster!, metric, windowMinutes),
    enabled: Boolean(cluster),
    refetchInterval: 15_000,
  })

  if (!cluster) return <NoCluster />

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-body">{t('nav.metrics')}</h1>
        <p className="mt-1 text-sm text-muted">{t('metrics.subtitle')}</p>
      </div>

      {status.data && !status.data.enabled && (
        <Banner tone="warn" title={t('metrics.samplerOffTitle')}>
          {t('metrics.samplerOffBody')}
        </Banner>
      )}

      {status.data?.last_error && (
        <Banner tone="warn" title={t('metrics.samplerErrorTitle')}>
          {status.data.last_error}
        </Banner>
      )}

      {status.data?.enabled && (
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-subtle bg-surface px-4 py-3">
            <dt className="text-xs text-muted">{t('metrics.samplerInterval')}</dt>
            <dd className="mt-0.5 text-sm font-medium text-body tabular">
              {status.data.interval_seconds}s
            </dd>
          </div>
          <div className="rounded-lg border border-subtle bg-surface px-4 py-3">
            <dt className="text-xs text-muted">{t('metrics.retention')}</dt>
            <dd className="mt-0.5 text-sm font-medium text-body tabular">
              {status.data.retention_days}d
            </dd>
          </div>
          <div className="rounded-lg border border-subtle bg-surface px-4 py-3">
            <dt className="text-xs text-muted">{t('metrics.lastSample')}</dt>
            <dd className="mt-0.5 text-sm font-medium text-body">
              {status.data.last_run_at ? formatRelative(status.data.last_run_at) : '—'}
            </dd>
          </div>
          <div className="rounded-lg border border-subtle bg-surface px-4 py-3">
            <dt className="text-xs text-muted">{t('metrics.prometheus')}</dt>
            <dd className="mt-0.5 text-sm font-medium text-body">
              {status.data.prometheus_enabled
                ? t('metrics.prometheusOn')
                : t('metrics.prometheusOff')}
            </dd>
          </div>
        </dl>
      )}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-body">{t('metrics.heatmapTitle')}</h2>
          <div className="flex items-center gap-2">
            <div role="group" aria-label={t('metrics.metric')} className="flex">
              {(['throughput', 'lag'] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={metric === option}
                  onClick={() => setMetric(option)}
                  className={`border px-2 py-1 text-xs first:rounded-l last:rounded-r ${
                    metric === option
                      ? 'border-brand bg-brand-tint font-medium text-brand'
                      : 'border-subtle text-muted hover:bg-surface-sunken'
                  }`}
                >
                  {t(`metrics.${option}`)}
                </button>
              ))}
            </div>
            <label htmlFor="window" className="sr-only">
              {t('metrics.window')}
            </label>
            <select
              id="window"
              value={windowMinutes}
              onChange={(event) => setWindowMinutes(Number(event.target.value))}
              className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
            >
              {WINDOWS.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes < 60 ? `${minutes}m` : `${minutes / 60}h`}
                </option>
              ))}
            </select>
          </div>
        </div>

        <p className="text-xs text-muted">{t('metrics.heatmapHint')}</p>

        <div className="rounded-lg border border-subtle bg-surface p-3">
          {heatmap.isPending ? (
            <Skeleton className="h-48 w-full" />
          ) : heatmap.data && heatmap.data.cells.length > 0 ? (
            <PartitionHeatmap heatmap={heatmap.data} />
          ) : (
            <EmptyState
              title={t('metrics.noSamples')}
              body={t('metrics.noSamplesHelp', {
                seconds: status.data?.interval_seconds ?? 30,
              })}
            />
          )}
        </div>
      </section>
    </div>
  )
}
