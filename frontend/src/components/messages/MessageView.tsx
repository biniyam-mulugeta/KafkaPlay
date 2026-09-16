import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { KafkaMessage, Payload } from '@/lib/api'
import { formatBytes, formatTimestamp } from '@/lib/format'
import { StatusPill } from '@/components/states/StatusPill'

function PayloadBlock({ payload, label }: { payload: Payload; label: string }) {
  const { t } = useTranslation()

  const rendered =
    payload.format === 'null'
      ? null
      : payload.format === 'json' || payload.format === 'avro' || payload.format === 'protobuf'
        ? JSON.stringify(payload.value, null, 2)
        : String(payload.value ?? '')

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted">{label}</span>
        <span className="rounded border border-subtle px-1.5 py-0.5 text-[10px] font-medium text-muted">
          {payload.format}
        </span>
        {payload.schema_id !== null && (
          <span className="rounded border border-subtle px-1.5 py-0.5 text-[10px] text-muted">
            schema {payload.schema_id}
          </span>
        )}
        <span className="text-[10px] text-faint">{formatBytes(payload.size_bytes)}</span>
      </div>

      {payload.error && (
        <p className="rounded border-l-2 border-warn bg-warn-tint px-2 py-1 text-[11px]">
          <span aria-hidden="true" className="mr-1">
            ▲
          </span>
          {payload.error}
        </p>
      )}

      {rendered === null ? (
        <p className="text-xs text-faint">{t('messages.nullPayload')}</p>
      ) : (
        <pre className="max-h-80 overflow-auto rounded border border-subtle bg-surface-sunken p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">
          {rendered}
        </pre>
      )}
    </div>
  )
}

export function MessageDetail({ message }: { message: KafkaMessage }) {
  const { t } = useTranslation()
  const headers = Object.entries(message.headers)

  return (
    <div className="space-y-3 border-t border-subtle bg-surface p-3">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted">{t('topicDetail.partition')}</dt>
          <dd className="tabular">{message.partition}</dd>
        </div>
        <div>
          <dt className="text-muted">{t('messages.offset')}</dt>
          <dd className="tabular">{message.offset}</dd>
        </div>
        <div>
          <dt className="text-muted">{t('messages.timestamp')}</dt>
          <dd>{message.timestamp ? formatTimestamp(message.timestamp) : '—'}</dd>
        </div>
        <div>
          <dt className="text-muted">{t('messages.timestampType')}</dt>
          <dd>{message.timestamp_type ?? '—'}</dd>
        </div>
      </dl>

      <PayloadBlock payload={message.key} label={t('messages.key')} />
      <PayloadBlock payload={message.value} label={t('messages.value')} />

      <div className="space-y-1">
        <span className="text-xs font-medium text-muted">{t('messages.headers')}</span>
        {headers.length === 0 ? (
          <p className="text-xs text-faint">{t('messages.noHeaders')}</p>
        ) : (
          <dl className="rounded border border-subtle bg-surface-sunken p-2 text-[11px]">
            {headers.map(([name, value]) => (
              <div key={name} className="flex gap-2 font-mono">
                <dt className="text-muted">{name}</dt>
                <dd className="break-all">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  )
}

/** One row in the results list, expandable to the full record. */
export function MessageRow({ message }: { message: KafkaMessage }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const preview =
    message.value.format === 'json' ||
    message.value.format === 'avro' ||
    message.value.format === 'protobuf'
      ? JSON.stringify(message.value.value)
      : String(message.value.value ?? '')

  return (
    <li className="border-b border-subtle last:border-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-3 py-1.5 text-left hover:bg-surface-sunken"
      >
        <span aria-hidden="true" className="w-3 shrink-0 text-faint">
          {open ? '▾' : '▸'}
        </span>
        <span className="tabular w-10 shrink-0 text-xs text-muted">p{message.partition}</span>
        <span className="tabular w-24 shrink-0 text-xs text-muted">@{message.offset}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs">{preview}</span>
        {message.masked && (
          <StatusPill tone="neutral" label={t('messages.masked')} title={t('messages.maskedHint')} />
        )}
      </button>
      {open && <MessageDetail message={message} />}
    </li>
  )
}
