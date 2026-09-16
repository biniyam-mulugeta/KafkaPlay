import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { AppShell } from '@/components/layout/AppShell'
import { EmptyState } from '@/components/states/EmptyState'
import { ClusterProvider } from '@/lib/cluster'
import { ConsumerGroups } from '@/pages/ConsumerGroups'
import { Dashboards } from '@/pages/Dashboards'
import { FlowMapPage } from '@/pages/FlowMap'
import { GroupDetail } from '@/pages/GroupDetail'
import { Login } from '@/pages/Login'
import { Messages } from '@/pages/Messages'
import { Alerts } from '@/pages/Alerts'
import { Audit } from '@/pages/Audit'
import { Metrics } from '@/pages/Metrics'
import { Settings } from '@/pages/Settings'
import { Overview } from '@/pages/Overview'
import { Placeholder } from '@/pages/Placeholder'
import { Replication } from '@/pages/Replication'
import { TopicDetail } from '@/pages/TopicDetail'
import { Topics } from '@/pages/Topics'
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
    <ClusterProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Overview />} />
            <Route path="topics" element={<Topics />} />
            <Route path="topics/:topic" element={<TopicDetail />} />
            <Route path="consumer-groups" element={<ConsumerGroups />} />
            <Route path="consumer-groups/:groupId" element={<GroupDetail />} />
            <Route path="replication" element={<Replication />} />
            <Route path="messages" element={<Messages />} />
            <Route path="metrics" element={<Metrics />} />
            <Route path="dashboards" element={<Dashboards />} />
            <Route path="flow-map" element={<FlowMapPage />} />
            <Route path="schemas" element={<Placeholder titleKey="nav.schemas" milestone="M8" />} />
            <Route path="acls" element={<Placeholder titleKey="nav.acls" milestone="M8" />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="audit" element={<Audit />} />
            <Route path="settings" element={<Settings />} />
            <Route path="404" element={<NotFound />} />
            <Route path="*" element={<Navigate to="/404" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ClusterProvider>
  )
}
