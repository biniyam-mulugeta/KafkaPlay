/**
 * Display formatting.
 *
 * Numbers take thousands separators, and times are shown as relative plus
 * absolute in a configurable zone that defaults to Europe/Budapest.
 */

export const DEFAULT_TIMEZONE = 'Europe/Budapest'

let timezone = DEFAULT_TIMEZONE
let locale = 'en'

export function configureFormatting(options: { timezone?: string; locale?: string }): void {
  if (options.timezone) timezone = options.timezone
  if (options.locale) locale = options.locale
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale).format(value)
}

/** Byte sizes in binary units, which is what Kafka reports. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`
}

export function formatAbsolute(input: Date | number | string): string {
  const date = input instanceof Date ? input : new Date(input)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale, {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

const DIVISIONS: { amount: number; unit: Intl.RelativeTimeFormatUnit }[] = [
  { amount: 60, unit: 'second' },
  { amount: 60, unit: 'minute' },
  { amount: 24, unit: 'hour' },
  { amount: 7, unit: 'day' },
  { amount: 4.34524, unit: 'week' },
  { amount: 12, unit: 'month' },
  { amount: Number.POSITIVE_INFINITY, unit: 'year' },
]

export function formatRelative(input: Date | number | string, now: Date = new Date()): string {
  const date = input instanceof Date ? input : new Date(input)
  if (Number.isNaN(date.getTime())) return '—'

  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  let duration = (date.getTime() - now.getTime()) / 1000

  for (const division of DIVISIONS) {
    if (Math.abs(duration) < division.amount) {
      return formatter.format(Math.round(duration), division.unit)
    }
    duration /= division.amount
  }
  return formatAbsolute(date)
}

/** "3 minutes ago (2026-09-16 10:04:12)" */
export function formatTimestamp(input: Date | number | string): string {
  return `${formatRelative(input)} (${formatAbsolute(input)})`
}
