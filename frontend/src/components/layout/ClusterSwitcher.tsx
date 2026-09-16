import { useTranslation } from 'react-i18next'

import { useCluster } from '@/lib/cluster'

/** Header cluster selector. Hidden entirely when only one is configured. */
export function ClusterSwitcher() {
  const { t } = useTranslation()
  const { clusters, currentName, setCurrent } = useCluster()

  if (clusters.length === 0) return null

  if (clusters.length === 1) {
    const only = clusters[0]!
    return (
      <span className="flex items-center gap-1.5 text-xs text-muted">
        <span aria-hidden="true">◇</span>
        {only.label}
        {only.read_only && (
          <span className="rounded border border-warn px-1 py-0.5 text-[10px] text-warn">
            {t('clusters.readOnly')}
          </span>
        )}
      </span>
    )
  }

  return (
    <>
      <label htmlFor="cluster-select" className="sr-only">
        {t('clusters.switcher')}
      </label>
      <select
        id="cluster-select"
        value={currentName ?? ''}
        onChange={(event) => setCurrent(event.target.value)}
        className="rounded border border-subtle bg-surface px-2 py-1 text-xs text-body"
      >
        {clusters.map((cluster) => (
          <option key={cluster.name} value={cluster.name}>
            {cluster.label}
            {cluster.read_only ? ` (${t('clusters.readOnly')})` : ''}
          </option>
        ))}
      </select>
    </>
  )
}
