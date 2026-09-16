import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/states/EmptyState'

/**
 * Shown when no cluster is configured. A first run with an empty
 * clusters.yaml is a valid state, so this explains the next step rather than
 * presenting an error.
 */
export function NoCluster() {
  const { t } = useTranslation()
  return (
    <EmptyState
      title={t('clusters.none')}
      body={
        <>
          {t('clusters.noneHelp')}
          <code className="ml-1 rounded bg-surface-sunken px-1 py-0.5 font-mono text-xs">
            config/clusters.yaml
          </code>
        </>
      }
    />
  )
}
