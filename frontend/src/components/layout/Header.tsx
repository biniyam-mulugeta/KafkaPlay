import { useTranslation } from 'react-i18next'

import { useSession } from '@/lib/session'
import { LOCALE_LABELS, SUPPORTED_LOCALES, persistLocale, type Locale } from '@/i18n'
import { ClusterSwitcher } from '@/components/layout/ClusterSwitcher'

/** Logo slot: the crest is optional, so fall back to a text wordmark. */
function Brand() {
  const { meta } = useSession()
  const { logo, product_name: productName } = meta.theme

  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {logo ? (
        <img src={logo} alt="" aria-hidden="true" className="h-7 w-auto shrink-0" />
      ) : (
        <span
          aria-hidden="true"
          className="grid h-7 w-7 shrink-0 place-items-center rounded bg-brand text-xs font-bold text-brand-contrast"
        >
          {productName.slice(0, 2).toUpperCase()}
        </span>
      )}
      <span className="truncate text-sm font-semibold text-body">{productName}</span>
    </div>
  )
}

export function Header() {
  const { t, i18n } = useTranslation()
  const { meta, me, mode, setMode, signOut } = useSession()

  const nextMode = mode === 'dark' ? 'light' : 'dark'

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-subtle bg-surface px-4">
      <Brand />

      <div className="flex-1" />

      <ClusterSwitcher />

      {meta.read_only && (
        <span className="rounded border border-warn px-2 py-0.5 text-xs font-medium text-warn">
          {t('banner.readOnlyTitle')}
        </span>
      )}

      <label className="sr-only" htmlFor="locale-select">
        {t('common.language')}
      </label>
      <select
        id="locale-select"
        value={i18n.language}
        onChange={(event) => {
          const locale = event.target.value as Locale
          void i18n.changeLanguage(locale)
          persistLocale(locale)
        }}
        className="rounded border border-subtle bg-surface px-2 py-1 text-xs text-muted"
      >
        {SUPPORTED_LOCALES.map((locale) => (
          <option key={locale} value={locale}>
            {LOCALE_LABELS[locale]}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={() => setMode(nextMode)}
        aria-label={t(nextMode === 'dark' ? 'common.darkMode' : 'common.lightMode')}
        className="rounded border border-subtle px-2 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
      >
        <span aria-hidden="true">{mode === 'dark' ? '☾' : '☀'}</span>
      </button>

      {me && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">
            {me.username}
            <span className="ml-1 text-faint">({me.role})</span>
          </span>
          {meta.auth_mode !== 'none' && (
            <button
              type="button"
              onClick={() => void signOut()}
              className="rounded border border-subtle px-2 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
            >
              {t('common.signOut')}
            </button>
          )}
        </div>
      )}
    </header>
  )
}
