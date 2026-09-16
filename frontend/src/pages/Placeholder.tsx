import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/states/EmptyState'

/**
 * Stand-in for pages that land in a later milestone.
 *
 * This is not a stub endpoint -- it is an honest, routed page that tells the
 * user the feature is not built yet, which beats a dead link or a 404.
 */
export function Placeholder({ titleKey, milestone }: { titleKey: string; milestone: string }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-body">{t(titleKey)}</h1>
      <EmptyState
        title={t('empty.comingSoonTitle')}
        body={`${t('empty.comingSoonBody')} (${milestone})`}
      />
    </div>
  )
}
