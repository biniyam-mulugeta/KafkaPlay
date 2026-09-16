import { beforeEach, describe, expect, it } from 'vitest'

import {
  applyTheme,
  categoricalPalette,
  persistMode,
  resolveInitialMode,
  type ThemeInfo,
} from '@/theme/themeLoader'

function theme(overrides: Partial<ThemeInfo> = {}): ThemeInfo {
  return {
    name: 'kafkaplay',
    product_name: 'KafkaPlay',
    logo: null,
    favicon: null,
    colors: {
      light: { brand: '#054434', accent: '#fbab2c' },
      dark: { brand: '#4fbf8f' },
      categorical: ['#054434', '#fbab2c'],
    },
    fonts: {},
    ...overrides,
  }
}

describe('applyTheme', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('style')
    document.documentElement.removeAttribute('data-theme')
    localStorage.clear()
  })

  it('writes the light palette onto the root element', () => {
    applyTheme(theme(), 'light')
    const root = document.documentElement
    expect(root.dataset.theme).toBe('light')
    expect(root.style.getPropertyValue('--kp-brand')).toBe('#054434')
    expect(root.style.getPropertyValue('--kp-accent')).toBe('#fbab2c')
  })

  it('writes the dark palette in dark mode', () => {
    applyTheme(theme(), 'dark')
    expect(document.documentElement.style.getPropertyValue('--kp-brand')).toBe('#4fbf8f')
  })

  it('ignores token names that are not safe to inject', () => {
    applyTheme(theme({ colors: { light: { 'brand: red; --evil': 'x' } } }), 'light')
    expect(document.documentElement.getAttribute('style') ?? '').not.toContain('evil')
  })

  it('tolerates a theme with no colours at all', () => {
    expect(() => applyTheme(theme({ colors: {} }), 'light')).not.toThrow()
  })

  it('applies custom fonts when supplied', () => {
    applyTheme(theme({ fonts: { sans: 'Foo', mono: 'Bar' } }), 'light')
    expect(document.documentElement.style.getPropertyValue('--kp-font-sans')).toBe('Foo')
  })
})

describe('categoricalPalette', () => {
  it('uses the theme palette when present', () => {
    expect(categoricalPalette(theme())).toEqual(['#054434', '#fbab2c'])
  })

  it('falls back when the theme supplies none', () => {
    expect(categoricalPalette(theme({ colors: {} })).length).toBeGreaterThan(4)
  })

  it('falls back for a null theme', () => {
    expect(categoricalPalette(null).length).toBeGreaterThan(4)
  })
})

describe('colour mode preference', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips through storage', () => {
    persistMode('dark')
    expect(resolveInitialMode()).toBe('dark')
  })

  it('defaults to light when nothing is stored', () => {
    expect(resolveInitialMode()).toBe('light')
  })

  it('ignores a corrupt stored value', () => {
    localStorage.setItem('kafkaplay.color-mode', 'chartreuse')
    expect(resolveInitialMode()).toBe('light')
  })
})
