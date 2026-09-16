import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { AppShell } from '@/components/layout/AppShell'
import { EmptyState } from '@/components/states/EmptyState'
import { Login } from '@/pages/Login'
import { Overview } from '@/pages/Overview'
import { Placeholder } from '@/pages/Placeholder'
import { useSession } from '@/lib/session'

function NotFound() {
  const { t } = useTranslation()
  return <EmptyState title={t('errors.notFoundTitle')} body={t('errors.notFoundBody')} />
}

export function App() {
  const { needsLogin } = useSession()

  if (needsLogin) {
    return <Login />
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Overview />} />
          <Route path="topics" element={<Placeholder titleKey="nav.topics" milestone="M2" />} />
          <Route
            path="consumer-groups"
            element={<Placeholder titleKey="nav.consumerGroups" milestone="M2" />}
          />
          <Route
            path="replication"
            element={<Placeholder titleKey="nav.replication" milestone="M2" />}
          />
          <Route
            path="messages"
            element={<Placeholder titleKey="nav.messages" milestone="M3" />}
          />
          <Route
            path="dashboards"
            element={<Placeholder titleKey="nav.dashboards" milestone="M7" />}
          />
          <Route path="flow-map" element={<Placeholder titleKey="nav.flowMap" milestone="M7" />} />
          <Route path="schemas" element={<Placeholder titleKey="nav.schemas" milestone="M8" />} />
          <Route path="acls" element={<Placeholder titleKey="nav.acls" milestone="M8" />} />
          <Route path="alerts" element={<Placeholder titleKey="nav.alerts" milestone="M6" />} />
          <Route path="audit" element={<Placeholder titleKey="nav.audit" milestone="M5" />} />
          <Route path="settings" element={<Placeholder titleKey="nav.settings" milestone="M5" />} />
          <Route path="404" element={<NotFound />} />
          <Route path="*" element={<Navigate to="/404" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
