import type { ReactNode } from 'react'

export type BannerTone = 'info' | 'warn' | 'critical' | 'ok'

const TONES: Record<BannerTone, { wrapper: string; icon: string; label: string }> = {
  // Each tone carries an icon as well as a colour, so the meaning survives for
  // colour-blind users and in greyscale print.
  info: { wrapper: 'bg-info-tint text-body border-info', icon: 'ⓘ', label: 'Information' },
  ok: { wrapper: 'bg-ok-tint text-body border-ok', icon: '✓', label: 'Success' },
  warn: { wrapper: 'bg-warn-tint text-body border-warn', icon: '▲', label: 'Warning' },
  critical: { wrapper: 'bg-critical-tint text-body border-critical', icon: '■', label: 'Critical' },
}

export function Banner({
  tone,
  title,
  children,
  action,
}: {
  tone: BannerTone
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  const style = TONES[tone]
  return (
    <div
      role={tone === 'critical' || tone === 'warn' ? 'alert' : 'status'}
      className={`flex items-start gap-3 border-l-4 px-4 py-3 text-sm ${style.wrapper}`}
    >
      <span aria-hidden="true" className="mt-px leading-5">
        {style.icon}
      </span>
      <span className="sr-only">{style.label}:</span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{title}</p>
        {children ? <div className="mt-0.5 text-muted">{children}</div> : null}
      </div>
      {action}
    </div>
  )
}
