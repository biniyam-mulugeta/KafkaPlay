import { describe, expect, it } from 'vitest'

import offsetscope from '../../../themes/offsetscope/theme.json'
import neutral from '../../../themes/neutral/theme.json'

/**
 * Colour contrast is a correctness property, not a matter of taste, so it is
 * enforced here rather than left to a manual accessibility pass. A future
 * palette tweak that breaks readability fails the build.
 */

function luminance(hex: string): number {
  const value = hex.replace('#', '')
  const full = value.length === 3 ? value.split('').map((c) => c + c).join('') : value
  const channels = [0, 2, 4].map((offset) => parseInt(full.slice(offset, offset + 2), 16) / 255)
  const adjusted = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * adjusted[0]! + 0.7152 * adjusted[1]! + 0.0722 * adjusted[2]!
}

function ratio(a: string, b: string): number {
  const first = luminance(a)
  const second = luminance(b)
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
}

// The imported JSON has a precise literal type; widen it via unknown so the
// test can iterate tokens generically.
const THEMES = { offsetscope, neutral } as unknown as Record<
  string,
  { colors: Record<string, Record<string, string>> }
>

// Small text, so WCAG AA requires 4.5:1.
const TEXT_TOKENS = ['text', 'text-muted', 'ok', 'warn', 'critical', 'info']

describe('theme contrast', () => {
  for (const [name, theme] of Object.entries(THEMES)) {
    for (const mode of ['light', 'dark'] as const) {
      const colors = theme.colors[mode]!

      for (const token of TEXT_TOKENS) {
        it(`${name}/${mode}: ${token} is readable on the surface`, () => {
          const contrast = ratio(colors[token]!, colors.surface!)
          expect(contrast).toBeGreaterThanOrEqual(4.5)
        })
      }

      it(`${name}/${mode}: button text is readable on the brand fill`, () => {
        expect(ratio(colors['brand-contrast']!, colors.brand!)).toBeGreaterThanOrEqual(4.5)
      })

      it(`${name}/${mode}: body text is readable on the page background`, () => {
        expect(ratio(colors.text!, colors.bg!)).toBeGreaterThanOrEqual(4.5)
      })

      it(`${name}/${mode}: status colours are distinguishable from each other`, () => {
        // Colour is never the only signal in the UI, but statuses should still
        // not be near-identical to one another.
        const pairs: [string, string][] = [
          ['ok', 'warn'],
          ['ok', 'critical'],
          ['warn', 'critical'],
        ]
        for (const [left, right] of pairs) {
          expect(colors[left]).not.toBe(colors[right])
        }
      })
    }

    it(`${name}: supplies a categorical palette for charts`, () => {
      const categorical = theme.colors.categorical as unknown as string[]
      expect(categorical.length).toBeGreaterThanOrEqual(6)
      expect(new Set(categorical).size).toBe(categorical.length)
    })
  }
})
