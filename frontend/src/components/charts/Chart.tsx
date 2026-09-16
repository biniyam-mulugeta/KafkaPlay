/**
 * Minimal ECharts wrapper.
 *
 * ECharts is ~630 kB, so it is imported dynamically inside the effect rather
 * than at module scope. Pages without charts never download it, and the ones
 * that do pay for it once.
 *
 * Colours come from the live theme tokens, so charts follow the brand and the
 * light/dark toggle with no second palette to maintain.
 */

import { useEffect, useRef, useState } from 'react'
import type { ECharts, EChartsCoreOption } from 'echarts/core'

import { useSession } from '@/lib/session'

let loader: Promise<typeof import('echarts/core')> | null = null

/** Loads ECharts once and registers only the pieces this app uses. */
async function loadECharts(): Promise<typeof import('echarts/core')> {
  if (loader === null) {
    loader = (async () => {
      const [core, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ])
      core.use([
        charts.LineChart,
        charts.BarChart,
        charts.HeatmapChart,
        components.GridComponent,
        components.TooltipComponent,
        components.LegendComponent,
        components.TitleComponent,
        components.DataZoomComponent,
        components.VisualMapComponent,
        components.MarkLineComponent,
        renderers.CanvasRenderer,
      ])
      return core
    })()
  }
  return loader
}

function token(name: string, fallback: string): string {
  if (typeof getComputedStyle !== 'function') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

export function useChartTheme() {
  const { mode } = useSession()
  return {
    mode,
    brand: token('--kp-brand', '#054434'),
    accent: token('--kp-accent', '#fbab2c'),
    text: token('--kp-text-muted', '#5a6764'),
    faint: token('--kp-text-faint', '#8a9591'),
    border: token('--kp-border', '#dfe3e1'),
    surface: token('--kp-surface', '#ffffff'),
    ok: token('--kp-ok', '#1b7f4b'),
    warn: token('--kp-warn', '#b26a00'),
    critical: token('--kp-critical', '#b3261e'),
    info: token('--kp-info', '#1b5e9e'),
  }
}

export function Chart({
  option,
  height = 240,
  ariaLabel,
}: {
  option: EChartsCoreOption
  height?: number
  ariaLabel: string
}) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<ECharts | null>(null)
  const optionRef = useRef(option)
  const [ready, setReady] = useState(false)
  const { mode } = useSession()

  // Keep the latest option reachable from the init effect without making it a
  // dependency, which would tear the chart down on every render. Assigning in
  // an effect rather than during render keeps this a legal ref write.
  useEffect(() => {
    optionRef.current = option
  }, [option])

  useEffect(() => {
    let cancelled = false
    let observer: ResizeObserver | null = null

    void loadECharts().then((echarts) => {
      if (cancelled || !container.current) return
      // Recreate on theme change so axis and label colours follow the toggle.
      instance.current?.dispose()
      instance.current = echarts.init(container.current, undefined, { renderer: 'canvas' })
      instance.current.setOption(optionRef.current)
      setReady(true)

      observer = new ResizeObserver(() => instance.current?.resize())
      observer.observe(container.current)
    })

    return () => {
      cancelled = true
      observer?.disconnect()
      instance.current?.dispose()
      instance.current = null
    }
  }, [mode])

  useEffect(() => {
    if (!ready) return
    // notMerge keeps a shrinking series from leaving stale points behind.
    instance.current?.setOption(option, { notMerge: true })
  }, [option, ready])

  return (
    <div
      ref={container}
      role="img"
      aria-label={ariaLabel}
      style={{ height }}
      className="w-full"
    />
  )
}
