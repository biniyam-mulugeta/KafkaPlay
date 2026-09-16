import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'

import '@/theme/tokens.css'

import { App } from '@/App'
import { api, ApiError } from '@/lib/api'
import { configureFormatting } from '@/lib/format'
import { initI18n } from '@/i18n'
import { SessionProvider, fetchInitialMe } from '@/lib/session'
import { applyTheme, resolveInitialMode } from '@/theme/themeLoader'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The brief's 5s polling default; individual views can override.
      refetchInterval: 5000,
      staleTime: 2500,
      retry: (failureCount, error) => {
        // Never retry an auth or permission failure -- it will not improve.
        if (error instanceof ApiError && (error.isUnauthenticated || error.isForbidden)) {
          return false
        }
        return failureCount < 2
      },
    },
  },
})

/** Rendered when even /api/v1/meta cannot be reached. */
function FatalError(message: string): void {
  const root = document.getElementById('root')
  if (!root) return
  root.innerHTML = `
    <div style="font-family: system-ui, sans-serif; padding: 3rem; max-width: 34rem; margin: 0 auto;">
      <h1 style="font-size: 1rem; font-weight: 600;">Cannot reach the console backend</h1>
      <p style="color: #5a6764; font-size: 0.875rem; margin-top: 0.5rem;">${message}</p>
      <p style="color: #8a9591; font-size: 0.8125rem; margin-top: 1rem;">
        Check that the service is running and that /api/v1/meta is reachable.
      </p>
    </div>`
}

async function bootstrap(): Promise<void> {
  const container = document.getElementById('root')
  if (!container) throw new Error('#root is missing from index.html')

  let meta
  try {
    meta = await api.meta()
  } catch (error) {
    FatalError(error instanceof Error ? error.message : String(error))
    return
  }

  // Paint the correct theme before first render so there is no flash.
  applyTheme(meta.theme, resolveInitialMode())

  const i18n = initI18n(meta.default_locale)
  configureFormatting({ locale: i18n.language })

  const me = await fetchInitialMe()

  createRoot(container).render(
    <StrictMode>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <SessionProvider meta={meta} initialMe={me}>
            <App />
          </SessionProvider>
        </QueryClientProvider>
      </I18nextProvider>
    </StrictMode>,
  )
}

void bootstrap()
