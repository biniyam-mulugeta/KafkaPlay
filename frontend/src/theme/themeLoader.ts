/**
 * Applies a theme fetched from the backend onto the document.
 *
 * The bundle ships with the kafkaplay palette as a CSS fallback; this
 * overwrites the --kp-* custom properties at runtime so an operator can mount
 * their own themes/<name>/theme.json and rebrand without rebuilding the image.
 */

export type ColorMode = 'light' | 'dark'

export interface ThemeColors {
  light?: Record<string, string>
  dark?: Record<string, string>
  categorical?: string[]
}

export interface ThemeInfo {
  name: string
  product_name: string
  logo: string | null
  favicon: string | null
  colors: ThemeColors
  fonts: Record<string, string>
}

const STORAGE_KEY = 'kafkaplay.color-mode'

/** Token names are written into the DOM, so constrain them to a safe shape. */
const SAFE_TOKEN = /^[a-z0-9-]+$/

function applyTokens(root: HTMLElement, tokens: Record<string, string> | undefined): void {
  if (!tokens) return
  for (const [key, value] of Object.entries(tokens)) {
    if (!SAFE_TOKEN.test(key)) continue
    if (typeof value !== 'string') continue
    root.style.setProperty(`--kp-${key}`, value)
  }
}

export function applyTheme(theme: ThemeInfo, mode: ColorMode): void {
  const root = document.documentElement
  root.dataset.theme = mode
  applyTokens(root, mode === 'dark' ? theme.colors?.dark : theme.colors?.light)

  if (theme.fonts?.sans) root.style.setProperty('--kp-font-sans', theme.fonts.sans)
  if (theme.fonts?.mono) root.style.setProperty('--kp-font-mono', theme.fonts.mono)
}

export function categoricalPalette(theme: ThemeInfo | null): string[] {
  // Colourblind-safe default, used when a theme supplies no palette.
  const fallback = [
    '#054434',
    '#fbab2c',
    '#1b5e9e',
    '#8e44ad',
    '#00857a',
    '#c1553b',
    '#5b6e7f',
    '#7a9a01',
  ]
  const supplied = theme?.colors?.categorical
  return supplied && supplied.length > 0 ? supplied : fallback
}

/** Reads the stored preference, else the OS setting. */
export function resolveInitialMode(): ColorMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // Private mode or blocked storage: fall through to the OS preference.
  }
  if (typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark'
  }
  return 'light'
}

export function persistMode(mode: ColorMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    // A theme preference is a convenience; losing it must never break the app.
  }
}

/** Sets the tab icon from the theme's emoji, avoiding a binary asset. */
export function applyFavicon(favicon: string | null): void {
  if (!favicon) return
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">${favicon}</text></svg>`
  const href = `data:image/svg+xml,${encodeURIComponent(svg)}`
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  link.href = href
}
