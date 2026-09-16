import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import type { LagHistory } from '@/lib/api'
import { Chart, useChartTheme } from '@/components/charts/Chart'
import { StatusPill } from '@/components/states/StatusPill'
import { formatNumber } from '@/lib/format'

/** "catching up / stable / falling behind", with an ETA when it is meaningful. */
export function LagTrendPill({ history }: { history: LagHistory }) {
  const { t } = useTranslation()

  const tone =
    history.trend === 'catching_up'
      ? 'ok'
      : history.trend === 'falling_behind'
        ? 'critical'
        : history.trend === 'stable'
          ? 'neutral'
          : 'neutral'

  return (
    <div className="flex flex-wrap items-center gap-2">
      <StatusPill tone={tone} label={t(`metrics.trend.${history.trend}`)} />
      {history.lag_velocity !== null && (
        <span className="text-xs text-muted tabular">
          {history.lag_velocity > 0 ? '+' : ''}
          {history.lag_velocity.toFixed(1)} {t('metrics.perSecond')}
        </span>
      )}
      {history.eta_seconds !== null && history.eta_seconds > 0 && (
        <span className="text-xs text-muted">
          {t('metrics.eta', { duration: humanDuration(history.eta_seconds) })}
        </span>
      )}
    </div>
  )
}

function humanDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`
  return `${(seconds / 86400).toFixed(1)}d`
}

export function LagChart({ history }: { history: LagHistory }) {
  const { t } = useTranslation()
  const theme = useChartTheme()

  const option = useMemo(() => {
    const lag = history.lag.map((point) => [point.at, point.value])
    const consume = history.consume_rate.map((point) => [point.at, point.value])
    const produce = history.produce_rate.map((point) => [point.at, point.value])

    return {
      animation: false,
      grid: { left: 52, right: 56, top: 28, bottom: 28 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: theme.surface,
        borderColor: theme.border,
        textStyle: { color: theme.text, fontSize: 11 },
        // Crosshair so lag and rates can be read at the same instant.
        axisPointer: { type: 'cross', label: { backgroundColor: theme.text } },
      },
      legend: {
        top: 0,
        textStyle: { color: theme.text, fontSize: 11 },
        data: [t('metrics.lag'), t('metrics.consumeRate'), t('metrics.produceRate')],
      },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: { color: theme.faint, fontSize: 10 },
      },
      yAxis: [
        {
          type: 'value',
          name: t('metrics.lag'),
          nameTextStyle: { color: theme.faint, fontSize: 10 },
          axisLabel: { color: theme.faint, fontSize: 10 },
          splitLine: { lineStyle: { color: theme.border, opacity: 0.5 } },
        },
        {
          type: 'value',
          name: t('metrics.msgPerSec'),
          nameTextStyle: { color: theme.faint, fontSize: 10 },
          axisLabel: { color: theme.faint, fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: t('metrics.lag'),
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: lag,
          lineStyle: { width: 2, color: theme.brand },
          areaStyle: { color: theme.brand, opacity: 0.12 },
        },
        {
          name: t('metrics.consumeRate'),
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          showSymbol: false,
          data: consume,
          lineStyle: { width: 1.5, color: theme.info },
        },
        {
          name: t('metrics.produceRate'),
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          showSymbol: false,
          // Dashed so the two rate lines stay distinguishable without colour.
          data: produce,
          lineStyle: { width: 1.5, color: theme.accent, type: 'dashed' },
        },
      ],
    }
  }, [history, theme, t])

  if (history.sampled_points === 0) {
    return (
      <p className="rounded border border-dashed border-strong px-3 py-6 text-center text-xs text-muted">
        {t('metrics.noSamples')}
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <LagTrendPill history={history} />
        {history.current_lag !== null && (
          <span className="text-xs text-muted">
            {t('metrics.currentLag')}:{' '}
            <span className="tabular font-medium text-body">
              {formatNumber(history.current_lag)}
            </span>
          </span>
        )}
      </div>
      <Chart option={option} ariaLabel={t('metrics.lagChartLabel')} height={260} />
    </div>
  )
}
