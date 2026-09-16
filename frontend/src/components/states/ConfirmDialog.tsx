import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Typed confirmation for destructive actions.
 *
 * The operator must type the exact target name. That is deliberate friction:
 * these actions are unrecoverable, and a single misplaced click should not be
 * enough to trigger one.
 */
function DialogBody({
  title,
  body,
  confirmPhrase,
  confirmLabel,
  tone = 'critical',
  busy = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string
  body: ReactNode
  /** The exact string the operator must type. */
  confirmPhrase: string
  confirmLabel: string
  tone?: 'critical' | 'warn'
  busy?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  // Mounted only while open, so this starts empty every time without an
  // effect resetting it.
  const [typed, setTyped] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // Focus the field so the keyboard path works without a mouse.
    const handle = window.setTimeout(() => inputRef.current?.focus(), 0)
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.clearTimeout(handle)
      window.removeEventListener('keydown', onKey)
    }
  }, [onCancel])

  const matches = typed === confirmPhrase
  const accent = tone === 'critical' ? 'border-critical' : 'border-warn'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'var(--kp-overlay)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
    >
      <div className={`w-full max-w-md rounded-lg border-t-4 bg-surface shadow-lg ${accent}`}>
        <div className="space-y-3 p-5">
          <h2 id="confirm-title" className="text-base font-semibold text-body">
            {title}
          </h2>

          <div className="text-sm text-muted">{body}</div>

          {error && (
            <p role="alert" className="rounded border-l-4 border-critical bg-critical-tint px-3 py-2 text-sm">
              <span aria-hidden="true" className="mr-1.5">■</span>
              {error}
            </p>
          )}

          <div>
            <label htmlFor="confirm-input" className="block text-xs font-medium text-muted">
              {t('confirm.typeToConfirm', { phrase: confirmPhrase })}
            </label>
            <input
              id="confirm-input"
              ref={inputRef}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              className="mt-1 w-full rounded border border-subtle bg-surface px-3 py-2 font-mono text-sm"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-subtle px-5 py-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded border border-subtle px-3 py-1.5 text-sm text-muted hover:bg-surface-sunken hover:text-body"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!matches || busy}
            className={`rounded px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40 ${
              tone === 'critical'
                ? 'bg-critical hover:opacity-90'
                : 'bg-warn hover:opacity-90'
            }`}
          >
            {busy ? t('confirm.working') : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}


/**
 * Only mounts the dialog while it is open, which keeps the typed-confirmation
 * field empty on each use without an effect that resets it.
 */
export function ConfirmDialog({
  open,
  ...props
}: {
  open: boolean
  title: string
  body: ReactNode
  confirmPhrase: string
  confirmLabel: string
  tone?: 'critical' | 'warn'
  busy?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}) {
  if (!open) return null
  return <DialogBody {...props} />
}
