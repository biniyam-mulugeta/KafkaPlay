import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import type { Heatmap } from '@/lib/api'
import { Chart, useChartTheme } from '@/components/charts/Chart'

/**
 * Topics x partitions, coloured by throughput or lag.
 *
 * A sequential single-hue ramp, so ordering is readable without relying on
 * colour discrimination, and the axis labels carry the same information for
 * anyone using a screen reader via the data table alternative.
 */
export function PartitionHeatmap({ heatmap }: { heatmap: Heatmap }) {
  const { t } = useTranslation()
  const theme = useChartTheme()

  const option = useMemo(() => {
    const partitions = Array.from({ length: heatmap.max_partition + 1 }, (_, i) => String(i))
    const data = heatmap.cells.map((cell) => [
      cell.partition,
      heatmap.topics.indexOf(cell.topic),
      cell.value,
    ])

    return {
      animation: false,
      grid: { left: 110, right: 24, top: 10, bottom: 56 },
      tooltip: {
        position: 'top',
        backgroundColor: theme.surface,
        borderColor: theme.border,
        textStyle: { color: theme.text, fontSize: 11 },
        formatter: (item: { data: [number, number, number] }) =>
          `${heatmap.topics[item.data[1]]} · p${item.data[0]}<br/>` +
          `<strong>${item.data[2]}</strong> ${
            heatmap.metric === 'lag' ? t('metrics.messages') : t('metrics.msgPerSec')
          }`,
      },
      xAxis: {
        type: 'category',
        data: partitions,
        name: t('topicDetail.partition'),
        nameLocation: 'middle',
        nameGap: 28,
        nameTextStyle: { color: theme.faint, fontSize: 10 },
        axisLabel: { color: theme.faint, fontSize: 10 },
        splitArea: { show: true },
      },
      yAxis: {
        type: 'category',
        data: heatmap.topics,
        axisLabel: { color: theme.text, fontSize: 10 },
        splitArea: { show: true },
      },
      visualMap: {
        min: 0,
        max: heatmap.max_value || 1,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        textStyle: { color: theme.faint, fontSize: 10 },
        inRange: {
          // Single-hue ramp from the surface colour to the brand.
          color: [theme.surface, theme.brand],
        },
      },
      series: [
        {
          type: 'heatmap',
          data,
          label: { show: false },
          itemStyle: { borderColor: theme.border, borderWidth: 1 },
          emphasis: { itemStyle: { borderColor: theme.accent, borderWidth: 2 } },
        },
      ],
    }
  }, [heatmap, theme, t])

  if (heatmap.cells.length === 0) {
    return (
      <p className="rounded border border-dashed border-strong px-3 py-6 text-center text-xs text-muted">
        {t('metrics.noSamples')}
      </p>
    )
  }

  return (
    <Chart
      option={option}
      ariaLabel={t('metrics.heatmapLabel')}
      height={Math.max(180, heatmap.topics.length * 34 + 96)}
    />
  )
}
