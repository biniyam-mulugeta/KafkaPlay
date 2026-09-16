import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '@/lib/api'
import { useSession } from '@/lib/session'

export function Login() {
  const { t } = useTranslation()
  const { meta, signIn } = useSession()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await signIn(username, password)
    } catch (caught) {
      // A failed login must not distinguish "no such user" from "wrong
      // password"; the backend already returns one message for both.
      setError(
        caught instanceof ApiError && caught.isUnauthenticated
          ? t('login.invalid')
          : t('login.unavailable'),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          {meta.theme.logo ? (
            <img src={meta.theme.logo} alt="" aria-hidden="true" className="h-9 w-auto" />
          ) : (
            <span
              aria-hidden="true"
              className="grid h-9 w-9 place-items-center rounded bg-brand text-sm font-bold text-brand-contrast"
            >
              {meta.theme.product_name.slice(0, 2).toUpperCase()}
            </span>
          )}
          <span className="text-lg font-semibold text-body">{meta.theme.product_name}</span>
        </div>

        <form
          onSubmit={(event) => void onSubmit(event)}
          className="rounded-lg border border-subtle bg-surface p-6 shadow-sm"
        >
          <h1 className="text-base font-semibold text-body">{t('login.title')}</h1>
          <p className="mt-1 text-sm text-muted">
            {t('login.subtitle', { product: meta.theme.product_name })}
          </p>

          {error && (
            <p
              role="alert"
              className="mt-4 rounded border-l-4 border-critical bg-critical-tint px-3 py-2 text-sm"
            >
              <span aria-hidden="true" className="mr-1.5">
                ■
              </span>
              {error}
            </p>
          )}

          <div className="mt-4 space-y-3">
            <div>
              <label htmlFor="username" className="block text-xs font-medium text-muted">
                {t('common.username')}
              </label>
              <input
                id="username"
                name="username"
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="mt-1 w-full rounded border border-subtle bg-surface px-3 py-2 text-sm text-body"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-xs font-medium text-muted">
                {t('common.password')}
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-1 w-full rounded border border-subtle bg-surface px-3 py-2 text-sm text-body"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={busy}
            className="mt-5 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-60"
          >
            {busy ? t('login.submitting') : t('common.signIn')}
          </button>
        </form>
      </div>
    </div>
  )
}
