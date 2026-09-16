import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, type AuditEntry, type AuditResult } from '@/lib/api'
import { formatTimestamp } from '@/lib/format'
import { DataTable, type Column } from '@/components/table/DataTable'
import { EmptyState, TableSkeleton } from '@/components/states/EmptyState'
import { StatusPill } from '@/components/states/StatusPill'
import { useSession } from '@/lib/session'

const RESULT_TONES: Record<AuditResult, 'ok' | 'warn' | 'critical'> = {
  success: 'ok',
  denied: 'warn',
  failed: 'critical',
}

function Snapshot({ label, json }: { label: string; json: string | null }) {
  if (!json) return null
  let pretty = json
  try {
    pretty = JSON.stringify(JSON.parse(json), null, 2)
  } catch {
    // Not JSON; show it as stored.
  }
  return (
    <div>
      <span className="text-[11px] font-medium text-muted">{label}</span>
      <pre className="mt-0.5 max-h-48 overflow-auto rounded bg-surface-sunken p-2 font-mono text-[11px] whitespace-pre-wrap break-all">
        {pretty}
      </pre>
    </div>
  )
}

export function Audit() {
  const { t } = useTranslation()
  const { me } = useSession()
  const [days, setDays] = useState(30)
  const [result, setResult] = useState<AuditResult | ''>('')
  const [expanded, setExpanded] = useState<number | null>(null)

  const query = useQuery({
    queryKey: ['audit', days, result],
    queryFn: () => api.audit({ days, result: result || undefined, limit: 500 }),
    refetchInterval: 30_000,
  })

  // The endpoint is admin-only; say so rather than showing an empty table.
  if (me && me.role !== 'admin') {
    return (
      <EmptyState
        icon="⚿"
        title={t('errors.forbiddenTitle')}
        body={t('audit.adminOnly')}
      />
    )
  }

  const columns: Column<AuditEntry>[] = [
    {
      key: 'at',
      header: t('audit.when'),
      sortValue: (row) => row.at,
      render: (row) => <span className="text-xs text-muted">{formatTimestamp(row.at)}</span>,
    },
    {
      key: 'who',
      header: t('audit.who'),
      sortValue: (row) => row.username,
      render: (row) => (
        <span className="text-xs">
          {row.username}
          <span className="ml-1 text-faint">({row.role})</span>
        </span>
      ),
    },
    {
      key: 'action',
      header: t('audit.action'),
      sortValue: (row) => row.action,
      render: (row) => <span className="font-mono text-xs">{row.action}</span>,
    },
    {
      key: 'target',
      header: t('audit.target'),
      render: (row) => (
        <span className="font-mono text-xs text-muted">{row.target ?? '—'}</span>
      ),
    },
    {
      key: 'result',
      header: t('audit.result'),
      sortValue: (row) => row.result,
      render: (row) => <StatusPill tone={RESULT_TONES[row.result]} label={row.result} />,
    },
    {
      key: 'detail',
      header: '',
      render: (row) =>
        row.before || row.after || row.detail ? (
          <button
            type="button"
            onClick={() => setExpanded(expanded === row.id ? null : row.id)}
            aria-expanded={expanded === row.id}
            className="text-xs text-brand hover:underline"
          >
            {expanded === row.id ? t('audit.hide') : t('audit.details')}
          </button>
        ) : null,
    },
  ]

  const entries = query.data?.entries ?? []
  const detail = entries.find((entry) => entry.id === expanded)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-body">{t('nav.audit')}</h1>
          <p className="mt-1 text-sm text-muted">{t('audit.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="audit-days" className="sr-only">
            {t('audit.window')}
          </label>
          <select
            id="audit-days"
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
          >
            {[1, 7, 30, 90, 365].map((value) => (
              <option key={value} value={value}>
                {t('audit.lastDays', { count: value })}
              </option>
            ))}
          </select>

          <label htmlFor="audit-result" className="sr-only">
            {t('audit.result')}
          </label>
          <select
            id="audit-result"
            value={result}
            onChange={(event) => setResult(event.target.value as AuditResult | '')}
            className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
          >
            <option value="">{t('audit.allResults')}</option>
            <option value="success">success</option>
            <option value="denied">denied</option>
            <option value="failed">failed</option>
          </select>

          <a
            href={`/api/v1/audit/export?days=${days}`}
            className="rounded border border-subtle px-2 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
          >
            {t('audit.exportCsv')}
          </a>
        </div>
      </div>

      {query.isPending ? (
        <TableSkeleton rows={8} />
      ) : (
        <>
          <DataTable
            rows={entries}
            columns={columns}
            getRowKey={(row) => String(row.id)}
            initialSortKey="at"
            emptyState={<EmptyState title={t('audit.none')} body={t('audit.noneHelp')} />}
          />

          {detail && (
            <div className="space-y-2 rounded-lg border border-subtle bg-surface p-4">
              <h2 className="text-sm font-semibold text-body">
                {detail.action}
                {detail.target ? ` · ${detail.target}` : ''}
              </h2>
              {detail.detail && <p className="text-xs text-muted">{detail.detail}</p>}
              {detail.source_ip && (
                <p className="text-[11px] text-faint">
                  {t('audit.sourceIp')}: <span className="font-mono">{detail.source_ip}</span>
                </p>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <Snapshot label={t('audit.before')} json={detail.before} />
                <Snapshot label={t('audit.after')} json={detail.after} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
