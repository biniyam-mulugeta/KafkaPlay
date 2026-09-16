import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api } from '@/lib/api'
import { EmptyState, TableSkeleton } from '@/components/states/EmptyState'
import { useSession } from '@/lib/session'

/**
 * M1 overview: confirms the console is wired up and lists configured clusters.
 * Broker counts, controller state and partition health arrive in M2.
 */
export function Overview() {
  const { t } = useTranslation()
  const { meta } = useSession()

  const clusters = useQuery({
    queryKey: ['clusters'],
    queryFn: api.clusters,
  })

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-body">{t('nav.overview')}</h1>
        <p className="mt-1 text-sm text-muted">
          {meta.app_name} v{meta.version}
        </p>
      </div>

      {clusters.isPending && <TableSkeleton rows={3} />}

      {clusters.isError && (
        <EmptyState
          title={t('errors.genericTitle')}
          body={t('errors.genericBody')}
          icon="▲"
          action={
            <button
              type="button"
              onClick={() => void clusters.refetch()}
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover"
            >
              {t('common.retry')}
            </button>
          }
        />
      )}

      {clusters.isSuccess && clusters.data.clusters.length === 0 && (
        <EmptyState title={t('clusters.none')} body={t('clusters.noneHelp')} />
      )}

      {clusters.isSuccess && clusters.data.clusters.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {clusters.data.clusters.map((cluster) => (
            <li
              key={cluster.name}
              className="rounded-lg border border-subtle bg-surface p-4"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="truncate text-sm font-medium text-body">{cluster.label}</span>
                {cluster.read_only && (
                  <span className="shrink-0 rounded border border-warn px-1.5 py-0.5 text-[10px] font-medium text-warn">
                    {t('clusters.readOnly')}
                  </span>
                )}
              </div>
              <dl className="mt-3 space-y-1 text-xs text-muted">
                <div className="flex justify-between gap-2">
                  <dt>Security</dt>
                  <dd className="tabular">{cluster.security_protocol}</dd>
                </div>
                {cluster.sasl_mechanism && (
                  <div className="flex justify-between gap-2">
                    <dt>SASL</dt>
                    <dd className="tabular">{cluster.sasl_mechanism}</dd>
                  </div>
                )}
                <div className="flex justify-between gap-2">
                  <dt>Schema Registry</dt>
                  <dd>{cluster.has_schema_registry ? 'yes' : 'no'}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
