import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { CommandPalette, useCommandPalette } from '@/components/layout/CommandPalette'
import { Header } from '@/components/layout/Header'
import { Sidebar } from '@/components/layout/Sidebar'
import { Banner } from '@/components/states/Banner'
import { useSession } from '@/lib/session'

export function AppShell() {
  const { t } = useTranslation()
  const { meta } = useSession()
  const [collapsed, setCollapsed] = useState(false)
  const palette = useCommandPalette()

  return (
    <div className="flex h-screen flex-col bg-bg">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>

      <Header onOpenPalette={() => palette.setOpen(true)} />

      {/* A wide-open console is not something to mention quietly once. */}
      {meta.insecure_no_auth && (
        <Banner tone="critical" title={t('banner.noAuthTitle')}>
          {t('banner.noAuthBody')}
        </Banner>
      )}

      <div className="flex min-h-0 flex-1">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
        <main id="main" className="min-w-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>

      <CommandPalette open={palette.open} onClose={() => palette.setOpen(false)} />
    </div>
  )
}
