import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import type { PanelResult } from '@/lib/api'
import { Chart, useChartTheme } from '@/components/charts/Chart'
import { formatNumber } from '@/lib/format'

/** Renders whichever visualisation a panel asked for. */
export function PanelChart({ result }: { result: PanelResult }) {
  const { t } = useTranslation()
  const theme = useChartTheme()

  const option = useMemo(() => {
    const base = {
      animation: false,
      grid: { left: 56, right: 20, top: 16, bottom: 48 },
      tooltip: {
        backgroundColor: theme.surface,
        borderColor: theme.border,
        textStyle: { color: theme.text, fontSize: 11 },
      },
    }

    if (result.type === 'throughput') {
      return {
        ...base,
        tooltip: { ...base.tooltip, trigger: 'axis', axisPointer: { type: 'cross' } },
        xAxis: {
          type: 'time',
          axisLine: { lineStyle: { color: theme.border } },
          axisLabel: { color: theme.faint, fontSize: 10 },
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: theme.faint, fontSize: 10 },
          splitLine: { lineStyle: { color: theme.border, opacity: 0.5 } },
        },
        series: [
          {
            type: 'line',
            smooth: true,
            showSymbol: false,
            data: result.series.map((point) => [point.at, point.messages_per_second]),
            lineStyle: { width: 2, color: theme.brand },
            areaStyle: { color: theme.brand, opacity: 0.12 },
          },
        ],
      }
    }

    // Bar-shaped panels: split_by, top_n and histogram.
    const isHistogram = result.type === 'histogram'
    return {
      ...base,
      tooltip: { ...base.tooltip, trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: result.buckets.map((bucket) => bucket.label),
        axisLabel: {
          color: theme.faint,
          fontSize: 10,
          rotate: result.buckets.length > 8 ? 35 : 0,
          // Long identifiers are common in top-N panels.
          formatter: (label: string) =>
            label.length > 18 ? `${label.slice(0, 16)}…` : label,
        },
        axisLine: { lineStyle: { color: theme.border } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: theme.faint, fontSize: 10 },
        splitLine: { lineStyle: { color: theme.border, opacity: 0.5 } },
      },
      series: [
        {
          type: 'bar',
          data: result.buckets.map((bucket) => bucket.value),
          itemStyle: { color: theme.brand, borderRadius: isHistogram ? 0 : [2, 2, 0, 0] },
          barCategoryGap: isHistogram ? '2%' : '30%',
          // Threshold markers, e.g. an alerting cut-off on a score histogram.
          markLine: result.thresholds.length
            ? {
                silent: true,
                symbol: 'none',
                lineStyle: { color: theme.accent, width: 2, type: 'dashed' },
                label: { color: theme.accent, fontSize: 10, formatter: '{c}' },
                data: result.thresholds.map((value) => ({
                  xAxis: result.buckets.findIndex(
                    (bucket) => Number(bucket.label) >= value,
                  ),
                })),
              }
            : undefined,
        },
      ],
    }
  }, [result, theme])

  if (result.error) {
    return (
      <p className="rounded border-l-4 border-warn bg-warn-tint px-3 py-2 text-xs">
        <span aria-hidden="true" className="mr-1.5">
          ▲
        </span>
        {result.error}
      </p>
    )
  }

  if (result.type === 'stat') {
    return (
      <div className="flex h-full min-h-24 flex-col items-center justify-center">
        <div className="tabular text-3xl font-semibold text-brand">
          {result.stat === null ? '—' : formatNumber(Math.round(result.stat * 100) / 100)}
        </div>
        {result.unit && <div className="mt-1 text-xs text-muted">{result.unit}</div>}
      </div>
    )
  }

  const empty =
    result.type === 'throughput' ? result.series.length === 0 : result.buckets.length === 0

  if (empty) {
    return (
      <p className="py-8 text-center text-xs text-muted">{t('dashboards.noPanelData')}</p>
    )
  }

  return <Chart option={option} ariaLabel={result.title} height={200} />
}
