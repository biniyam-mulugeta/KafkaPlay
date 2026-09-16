import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '@/lib/api'
import { useSession } from '@/lib/session'

type Mode = 'signin' | 'register'

export function Login() {
  const { t } = useTranslation()
  const { meta, signIn, signUp } = useSession()

  // A brand-new deployment has no accounts, so registration is the only thing
  // that makes sense to show first.
  const [mode, setMode] = useState<Mode>(meta.signup_is_first_user ? 'register' : 'signin')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const registering = mode === 'register'
  const tooShort = registering && password.length > 0 && password.length < 12
  const mismatch = registering && confirm.length > 0 && confirm !== password

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)

    if (registering && password !== confirm) {
      setError(t('login.passwordsDiffer'))
      return
    }

    setBusy(true)
    try {
      if (registering) {
        await signUp(username, password)
      } else {
        await signIn(username, password)
      }
    } catch (caught) {
      if (caught instanceof ApiError) {
        // A failed login must not distinguish "no such user" from "wrong
        // password"; the backend already returns one message for both.
        setError(
          caught.isUnauthenticated && !registering ? t('login.invalid') : caught.message,
        )
      } else {
        setError(t('login.unavailable'))
      }
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
          <h1 className="text-base font-semibold text-body">
            {registering ? t('login.createAccount') : t('login.title')}
          </h1>

          <p className="mt-1 text-sm text-muted">
            {meta.signup_is_first_user
              ? t('login.firstUserHint')
              : registering
                ? t('login.registerHint')
                : t('login.subtitle', { product: meta.theme.product_name })}
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
                autoComplete={registering ? 'new-password' : 'current-password'}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-describedby={registering ? 'password-rule' : undefined}
                className="mt-1 w-full rounded border border-subtle bg-surface px-3 py-2 text-sm text-body"
              />
              {registering && (
                <p
                  id="password-rule"
                  className={`mt-1 text-[11px] ${tooShort ? 'text-warn' : 'text-faint'}`}
                >
                  {t('login.passwordRule')}
                </p>
              )}
            </div>

            {registering && (
              <div>
                <label htmlFor="confirm" className="block text-xs font-medium text-muted">
                  {t('login.confirmPassword')}
                </label>
                <input
                  id="confirm"
                  name="confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  className="mt-1 w-full rounded border border-subtle bg-surface px-3 py-2 text-sm text-body"
                />
                {mismatch && (
                  <p className="mt-1 text-[11px] text-warn">{t('login.passwordsDiffer')}</p>
                )}
              </div>
            )}
          </div>

          <button
            type="submit"
            disabled={busy || (registering && (tooShort || mismatch))}
            className="mt-5 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-60"
          >
            {busy
              ? registering
                ? t('login.creating')
                : t('login.submitting')
              : registering
                ? t('login.createAccount')
                : t('common.signIn')}
          </button>

          {/* Only offered when the backend says registration is actually open,
              so the form never promises something it will refuse. */}
          {meta.signup_available && !meta.signup_is_first_user && (
            <button
              type="button"
              onClick={() => {
                setMode(registering ? 'signin' : 'register')
                setError(null)
                setConfirm('')
              }}
              className="mt-3 w-full text-center text-xs text-brand hover:underline"
            >
              {registering ? t('login.haveAccount') : t('login.needAccount')}
            </button>
          )}
        </form>
      </div>
    </div>
  )
}
