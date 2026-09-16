import { useTranslation } from 'react-i18next'

import { AddClusterForm } from '@/components/admin/AddClusterForm'
import { useSession } from '@/lib/session'

/**
 * Shown when no cluster is configured.
 *
 * A first run with nothing configured is the normal path, not an error, so
 * this offers the form to fix it rather than just describing the problem.
 * Non-admins get the explanation without the form they cannot use.
 */
export function NoCluster() {
  const { t } = useTranslation()
  const { me } = useSession()
  const canAdd = me?.role === 'admin'

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-dashed border-strong bg-surface px-6 py-8 text-center">
        <span aria-hidden="true" className="text-3xl text-faint">
          ◇
        </span>
        <h2 className="mt-3 text-base font-semibold text-body">{t('addCluster.noneTitle')}</h2>
        <p className="mt-1 text-sm text-muted">
          {canAdd ? t('addCluster.noneBody') : t('clusters.noneHelp')}
        </p>
      </div>

      {canAdd && <AddClusterForm />}
    </div>
  )
}
