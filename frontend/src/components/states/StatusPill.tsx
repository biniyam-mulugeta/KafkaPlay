import type { Degraded, GroupState } from '@/lib/api'
import { Banner } from '@/components/states/Banner'

/**
 * Status is never conveyed by colour alone -- each pill carries a glyph too,
 * so it survives greyscale and colour-blindness.
 */
export function StatusPill({
  tone,
  label,
  title,
}: {
  tone: 'ok' | 'warn' | 'critical' | 'neutral'
  label: string
  title?: string
}) {
  const styles = {
    ok: { className: 'border-ok text-ok bg-ok-tint', glyph: '●' },
    warn: { className: 'border-warn text-warn bg-warn-tint', glyph: '▲' },
    critical: { className: 'border-critical text-critical bg-critical-tint', glyph: '■' },
    neutral: { className: 'border-subtle text-muted bg-surface-sunken', glyph: '○' },
  }[tone]

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium ${styles.className}`}
    >
      <span aria-hidden="true">{styles.glyph}</span>
      {label}
    </span>
  )
}

const GROUP_TONES: Record<GroupState, 'ok' | 'warn' | 'critical' | 'neutral'> = {
  stable: 'ok',
  empty: 'warn',
  preparing_rebalance: 'warn',
  completing_rebalance: 'warn',
  dead: 'critical',
  unknown: 'neutral',
}

export function GroupStatePill({ state }: { state: GroupState }) {
  return <StatusPill tone={GROUP_TONES[state] ?? 'neutral'} label={state.replace(/_/g, ' ')} />
}

/** Rendered whenever an API response carries a degraded block. */
export function DegradedBanner({ degraded }: { degraded: Degraded | null | undefined }) {
  if (!degraded) return null
  const tone = degraded.reason === 'unsupported' ? 'info' : 'warn'
  return (
    <Banner tone={tone} title={degraded.message}>
      {degraded.hint}
    </Banner>
  )
}
