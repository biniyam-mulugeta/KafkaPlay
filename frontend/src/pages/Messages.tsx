import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import {
  ApiError,
  api,
  type KafkaMessage,
  type SearchResponse,
  type StartFrom,
} from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { Banner } from '@/components/states/Banner'
import { EmptyState, TableSkeleton } from '@/components/states/EmptyState'
import { MessageRow } from '@/components/messages/MessageView'
import { NoCluster } from '@/components/states/NoCluster'
import { useTail } from '@/lib/tail'

const FILTER_EXAMPLES = [
  "value.status == 'failed'",
  'value.amount_cents > `10000`',
  "contains(value.path, '/admin')",
  "headers.source == 'gateway' && value.retries > `2`",
]

export function Messages() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const [params, setParams] = useSearchParams()

  const [topic, setTopic] = useState(params.get('topic') ?? '')
  const [startFrom, setStartFrom] = useState<StartFrom>('newest')
  const [offset, setOffset] = useState('')
  const [timestamp, setTimestamp] = useState('')
  const [filter, setFilter] = useState('')
  const [maxResults, setMaxResults] = useState(100)
  const [maxSeconds, setMaxSeconds] = useState(20)
  const [partitionText, setPartitionText] = useState('')

  const [result, setResult] = useState<SearchResponse | null>(null)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const tail = useTail(cluster, topic, filter)

  const topics = useQuery({
    queryKey: ['topics', cluster, false],
    queryFn: () => api.topics(cluster!, false),
    enabled: Boolean(cluster),
    refetchInterval: false,
  })

  // Keep the selected topic in the URL so a search is shareable.
  useEffect(() => {
    if (topic) setParams({ topic }, { replace: true })
  }, [topic, setParams])

  const partitions = useMemo(() => {
    const parsed = partitionText
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
      .map(Number)
      .filter((value) => Number.isInteger(value) && value >= 0)
    return parsed.length > 0 ? parsed : null
  }, [partitionText])

  async function runScan() {
    if (!cluster || !topic) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setScanning(true)
    setError(null)
    try {
      const response = await api.searchMessages(
        cluster,
        {
          topic,
          partitions,
          start_from: startFrom,
          offset: startFrom === 'offset' && offset ? Number(offset) : null,
          timestamp_ms:
            startFrom === 'timestamp' && timestamp ? new Date(timestamp).getTime() : null,
          filter: filter.trim() || null,
          max_results: maxResults,
          max_seconds: maxSeconds,
        },
        controller.signal,
      )
      setResult(response)
    } catch (caught) {
      if (controller.signal.aborted) return
      setError(caught instanceof ApiError ? caught.message : String(caught))
    } finally {
      if (!controller.signal.aborted) setScanning(false)
    }
  }

  function cancelScan() {
    abortRef.current?.abort()
    setScanning(false)
  }

  if (!cluster) return <NoCluster />

  const messages: KafkaMessage[] = tail.active ? tail.messages : (result?.messages ?? [])

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-body">{t('nav.messages')}</h1>

      <div className="space-y-3 rounded-lg border border-subtle bg-surface p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-48">
            <label htmlFor="topic" className="block text-xs font-medium text-muted">
              {t('topics.name')}
            </label>
            <select
              id="topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              className="mt-1 w-full rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
            >
              <option value="">{t('messages.selectTopic')}</option>
              {(topics.data?.topics ?? []).map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="start" className="block text-xs font-medium text-muted">
              {t('messages.startFrom')}
            </label>
            <select
              id="start"
              value={startFrom}
              onChange={(event) => setStartFrom(event.target.value as StartFrom)}
              className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
            >
              <option value="newest">{t('messages.newest')}</option>
              <option value="oldest">{t('messages.oldest')}</option>
              <option value="offset">{t('messages.fromOffset')}</option>
              <option value="timestamp">{t('messages.fromTimestamp')}</option>
            </select>
          </div>

          {startFrom === 'offset' && (
            <div>
              <label htmlFor="offset" className="block text-xs font-medium text-muted">
                {t('messages.offset')}
              </label>
              <input
                id="offset"
                type="number"
                min={0}
                value={offset}
                onChange={(event) => setOffset(event.target.value)}
                className="mt-1 w-28 rounded border border-subtle bg-surface px-2 py-1.5 text-sm tabular"
              />
            </div>
          )}

          {startFrom === 'timestamp' && (
            <div>
              <label htmlFor="ts" className="block text-xs font-medium text-muted">
                {t('messages.timestamp')}
              </label>
              <input
                id="ts"
                type="datetime-local"
                value={timestamp}
                onChange={(event) => setTimestamp(event.target.value)}
                className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
              />
            </div>
          )}

          <div>
            <label htmlFor="partitions" className="block text-xs font-medium text-muted">
              {t('messages.partitions')}
            </label>
            <input
              id="partitions"
              value={partitionText}
              onChange={(event) => setPartitionText(event.target.value)}
              placeholder={t('messages.allPartitions')}
              className="mt-1 w-32 rounded border border-subtle bg-surface px-2 py-1.5 text-sm tabular"
            />
          </div>
        </div>

        <div>
          <label htmlFor="filter" className="block text-xs font-medium text-muted">
            {t('messages.filter')}
          </label>
          <input
            id="filter"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder={FILTER_EXAMPLES[0]}
            className="mt-1 w-full rounded border border-subtle bg-surface px-2 py-1.5 font-mono text-sm"
          />
          <div className="mt-1 flex flex-wrap gap-1.5">
            {FILTER_EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setFilter(example)}
                className="rounded border border-subtle px-1.5 py-0.5 font-mono text-[10px] text-muted hover:bg-surface-sunken hover:text-body"
              >
                {example}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="maxResults" className="block text-xs font-medium text-muted">
              {t('messages.maxResults')}
            </label>
            <input
              id="maxResults"
              type="number"
              min={1}
              max={1000}
              value={maxResults}
              onChange={(event) => setMaxResults(Number(event.target.value))}
              className="mt-1 w-24 rounded border border-subtle bg-surface px-2 py-1.5 text-sm tabular"
            />
          </div>
          <div>
            <label htmlFor="maxSeconds" className="block text-xs font-medium text-muted">
              {t('messages.maxSeconds')}
            </label>
            <input
              id="maxSeconds"
              type="number"
              min={1}
              max={120}
              value={maxSeconds}
              onChange={(event) => setMaxSeconds(Number(event.target.value))}
              className="mt-1 w-24 rounded border border-subtle bg-surface px-2 py-1.5 text-sm tabular"
            />
          </div>

          <div className="flex-1" />

          {scanning ? (
            <button
              type="button"
              onClick={cancelScan}
              className="rounded border border-critical px-3 py-1.5 text-sm font-medium text-critical hover:bg-critical-tint"
            >
              {t('messages.cancel')}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void runScan()}
              disabled={!topic || tail.active}
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-50"
            >
              {t('messages.search')}
            </button>
          )}

          <button
            type="button"
            onClick={() => (tail.active ? tail.stop() : tail.start())}
            disabled={!topic || scanning}
            className={`rounded border px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${
              tail.active
                ? 'border-critical text-critical hover:bg-critical-tint'
                : 'border-subtle text-muted hover:bg-surface-sunken hover:text-body'
            }`}
          >
            {tail.active ? t('messages.stopTail') : t('messages.liveTail')}
          </button>

          {tail.active && (
            <button
              type="button"
              onClick={tail.togglePause}
              className="rounded border border-subtle px-3 py-1.5 text-sm text-muted hover:bg-surface-sunken hover:text-body"
            >
              {tail.paused ? t('messages.resume') : t('messages.pause')}
            </button>
          )}
        </div>
      </div>

      {error && <Banner tone="critical" title={t('errors.genericTitle')}>{error}</Banner>}
      {tail.error && <Banner tone="warn" title={t('messages.tailError')}>{tail.error}</Banner>}

      {result && !tail.active && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
          <span>
            {t('messages.resultSummary', {
              shown: formatNumber(result.messages.length),
              scanned: formatNumber(result.scanned),
              seconds: result.elapsed_seconds,
            })}
          </span>
          <span className="rounded border border-subtle px-1.5 py-0.5">
            {t(`messages.stopReason.${result.stop_reason}`)}
          </span>
          {result.masking_enabled && (
            <span className="rounded border border-subtle px-1.5 py-0.5">
              {t('messages.maskingOn')}
            </span>
          )}
        </div>
      )}

      {tail.active && (
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="relative flex h-2 w-2" aria-hidden="true">
            <span
              className={`absolute inline-flex h-2 w-2 rounded-full ${
                tail.paused ? 'bg-warn' : 'animate-ping bg-ok'
              }`}
            />
            <span
              className={`relative inline-flex h-2 w-2 rounded-full ${
                tail.paused ? 'bg-warn' : 'bg-ok'
              }`}
            />
          </span>
          {tail.paused ? t('messages.tailPaused') : t('messages.tailLive')}
          <span className="tabular">({formatNumber(tail.messages.length)})</span>
        </div>
      )}

      {scanning && <TableSkeleton rows={6} />}

      {!scanning && messages.length === 0 && (
        <EmptyState
          title={topic ? t('messages.noResults') : t('messages.selectTopicFirst')}
          body={topic ? t('messages.noResultsHelp') : t('messages.selectTopicHelp')}
        />
      )}

      {messages.length > 0 && (
        <ul className="overflow-hidden rounded-lg border border-subtle bg-surface">
          {messages.map((message) => (
            <MessageRow
              key={`${message.partition}-${message.offset}`}
              message={message}
            />
          ))}
        </ul>
      )}
    </div>
  )
}
