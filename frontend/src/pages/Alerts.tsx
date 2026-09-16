import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import {
  ApiError,
  api,
  type AlertFiring,
  type AlertKind,
  type AlertRule,
  type AlertSeverity,
} from '@/lib/api'
import { useCluster, useClusterName } from '@/lib/cluster'
import { formatNumber, formatTimestamp } from '@/lib/format'
import { Banner } from '@/components/states/Banner'
import { ConfirmDialog } from '@/components/states/ConfirmDialog'
import { DataTable, type Column } from '@/components/table/DataTable'
import { EmptyState, TableSkeleton } from '@/components/states/EmptyState'
import { StatusPill } from '@/components/states/StatusPill'
import { useSession } from '@/lib/session'

const SEVERITY_TONES: Record<AlertSeverity, 'ok' | 'warn' | 'critical' | 'neutral'> = {
  info: 'neutral',
  warning: 'warn',
  critical: 'critical',
}

function humanSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function NewRuleForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [kind, setKind] = useState<AlertKind>('lag_above')
  const [severity, setSeverity] = useState<AlertSeverity>('warning')
  const [threshold, setThreshold] = useState('1000')
  const [groupId, setGroupId] = useState('')
  const [topic, setTopic] = useState('')
  const [forSeconds, setForSeconds] = useState(60)
  const [error, setError] = useState<string | null>(null)

  const kinds = useQuery({ queryKey: ['alert-kinds'], queryFn: api.alertKinds })
  const groups = useQuery({
    queryKey: ['groups', cluster],
    queryFn: () => api.groups(cluster!, false),
    enabled: Boolean(cluster),
  })
  const topics = useQuery({
    queryKey: ['topics', cluster, false],
    queryFn: () => api.topics(cluster!, false),
    enabled: Boolean(cluster),
  })

  const selected = kinds.data?.find((item) => item.kind === kind)

  const create = useMutation({
    mutationFn: () =>
      api.createAlertRule({
        name,
        cluster,
        kind,
        severity,
        threshold: Number(threshold),
        group_id: selected?.needs_group ? groupId : null,
        topic: selected?.needs_topic ? topic : null,
        for_seconds: forSeconds,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
      onDone()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  return (
    <div className="space-y-3 rounded-lg border border-subtle bg-surface p-4">
      {error && <Banner tone="critical" title={t('errors.genericTitle')}>{error}</Banner>}

      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-48">
          <label htmlFor="rule-name" className="block text-xs font-medium text-muted">
            {t('alerts.ruleName')}
          </label>
          <input
            id="rule-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-1 w-full rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
          />
        </div>

        <div>
          <label htmlFor="rule-kind" className="block text-xs font-medium text-muted">
            {t('alerts.condition')}
          </label>
          <select
            id="rule-kind"
            value={kind}
            onChange={(event) => setKind(event.target.value as AlertKind)}
            className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
          >
            {(kinds.data ?? []).map((item) => (
              <option key={item.kind} value={item.kind}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="rule-threshold" className="block text-xs font-medium text-muted">
            {t('alerts.threshold')}
            {selected && <span className="ml-1 text-faint">({selected.threshold_hint})</span>}
          </label>
          <input
            id="rule-threshold"
            type="number"
            value={threshold}
            onChange={(event) => setThreshold(event.target.value)}
            className="mt-1 w-32 rounded border border-subtle bg-surface px-3 py-1.5 text-sm tabular"
          />
        </div>

        {selected?.needs_group && (
          <div>
            <label htmlFor="rule-group" className="block text-xs font-medium text-muted">
              {t('groups.groupId')}
            </label>
            <select
              id="rule-group"
              value={groupId}
              onChange={(event) => setGroupId(event.target.value)}
              className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
            >
              <option value="">{t('alerts.selectGroup')}</option>
              {(groups.data?.groups ?? []).map((group) => (
                <option key={group.group_id} value={group.group_id}>
                  {group.group_id}
                </option>
              ))}
            </select>
          </div>
        )}

        {selected?.needs_topic && (
          <div>
            <label htmlFor="rule-topic" className="block text-xs font-medium text-muted">
              {t('topics.name')}
            </label>
            <select
              id="rule-topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
            >
              <option value="">{t('messages.selectTopic')}</option>
              {(topics.data?.topics ?? []).map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label htmlFor="rule-severity" className="block text-xs font-medium text-muted">
            {t('alerts.severity')}
          </label>
          <select
            id="rule-severity"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as AlertSeverity)}
            className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
          >
            <option value="info">info</option>
            <option value="warning">warning</option>
            <option value="critical">critical</option>
          </select>
        </div>

        <div>
          <label htmlFor="rule-for" className="block text-xs font-medium text-muted">
            {t('alerts.forSeconds')}
          </label>
          <input
            id="rule-for"
            type="number"
            min={0}
            value={forSeconds}
            onChange={(event) => setForSeconds(Number(event.target.value))}
            className="mt-1 w-24 rounded border border-subtle bg-surface px-3 py-1.5 text-sm tabular"
          />
        </div>

        <button
          type="button"
          disabled={!name || !cluster || create.isPending}
          onClick={() => create.mutate()}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-50"
        >
          {t('alerts.createRule')}
        </button>
      </div>

      <p className="text-[11px] text-faint">{t('alerts.forSecondsHint')}</p>
    </div>
  )
}

export function Alerts() {
  const { t } = useTranslation()
  const { me, meta } = useSession()
  const { clusters } = useCluster()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [toDelete, setToDelete] = useState<AlertRule | null>(null)
  const [testResult, setTestResult] = useState<string | null>(null)

  const canEdit = me?.role === 'operator' || me?.role === 'admin'

  const rules = useQuery({ queryKey: ['alert-rules'], queryFn: api.alertRules })
  const firings = useQuery({
    queryKey: ['alert-firings'],
    queryFn: () => api.alertFirings(7),
    refetchInterval: 20_000,
  })

  const toggle = useMutation({
    mutationFn: (rule: AlertRule) => api.updateAlertRule(rule.id, { enabled: !rule.enabled }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteAlertRule(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
      setToDelete(null)
    },
  })

  const acknowledge = useMutation({
    mutationFn: (id: number) => api.acknowledgeFiring(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['alert-firings'] }),
  })

  const test = useMutation({
    mutationFn: api.testNotification,
    onSuccess: (data) =>
      setTestResult(
        Object.entries(data.results)
          .map(([sink, outcome]) => `${sink}: ${outcome}`)
          .join(' · '),
      ),
    onError: (caught) =>
      setTestResult(caught instanceof ApiError ? caught.message : String(caught)),
  })

  const ruleColumns: Column<AlertRule>[] = [
    {
      key: 'state',
      header: t('alerts.state'),
      sortValue: (row) => (row.state === 'firing' ? 0 : 1),
      render: (row) =>
        row.state === 'firing' ? (
          <StatusPill tone={SEVERITY_TONES[row.severity]} label={t('alerts.firing')} />
        ) : (
          <StatusPill tone="ok" label={t('alerts.ok')} />
        ),
    },
    {
      key: 'name',
      header: t('alerts.ruleName'),
      sortValue: (row) => row.name,
      render: (row) => (
        <span className="text-sm">
          {row.name}
          {!row.enabled && (
            <span className="ml-1.5 text-[10px] text-faint">{t('alerts.disabled')}</span>
          )}
        </span>
      ),
    },
    {
      key: 'condition',
      header: t('alerts.condition'),
      render: (row) => (
        <span className="text-xs text-muted">
          <span className="font-mono">{row.kind}</span> &gt; {formatNumber(row.threshold)}
          {row.group_id && <span className="ml-1 font-mono">· {row.group_id}</span>}
          {row.topic && <span className="ml-1 font-mono">· {row.topic}</span>}
        </span>
      ),
    },
    {
      key: 'current',
      header: t('alerts.currentValue'),
      align: 'right',
      sortValue: (row) => row.last_value,
      render: (row) => (
        <span className="tabular text-xs">
          {row.last_value === null ? '—' : formatNumber(Math.round(row.last_value))}
        </span>
      ),
    },
    {
      key: 'timing',
      header: t('alerts.timing'),
      render: (row) => (
        <span className="text-[11px] text-faint">
          {t('alerts.holdFor')} {humanSeconds(row.for_seconds)} · {t('alerts.cooldown')}{' '}
          {humanSeconds(row.cooldown_seconds)}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (row) =>
        canEdit ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => toggle.mutate(row)}
              className="text-xs text-brand hover:underline"
            >
              {row.enabled ? t('alerts.disable') : t('alerts.enable')}
            </button>
            <button
              type="button"
              onClick={() => setToDelete(row)}
              className="text-xs text-critical hover:underline"
            >
              {t('alerts.delete')}
            </button>
          </div>
        ) : null,
    },
  ]

  const firingColumns: Column<AlertFiring>[] = [
    {
      key: 'at',
      header: t('audit.when'),
      sortValue: (row) => row.at,
      render: (row) => <span className="text-xs text-muted">{formatTimestamp(row.at)}</span>,
    },
    {
      key: 'state',
      header: t('alerts.state'),
      render: (row) =>
        row.state === 'firing' ? (
          <StatusPill tone={SEVERITY_TONES[row.severity]} label={t('alerts.firing')} />
        ) : (
          <StatusPill tone="ok" label={t('alerts.resolved')} />
        ),
    },
    {
      key: 'rule',
      header: t('alerts.ruleName'),
      render: (row) => <span className="text-sm">{row.rule_name}</span>,
    },
    {
      key: 'message',
      header: t('alerts.message'),
      render: (row) => (
        <span className="text-xs text-muted">
          {row.message}
          {row.notify_error && (
            <span className="ml-1.5 text-warn" title={row.notify_error}>
              ▲ {t('alerts.notifyFailed')}
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'ack',
      header: '',
      render: (row) =>
        row.acknowledged_at ? (
          <span className="text-[11px] text-faint">
            {t('alerts.ackedBy', { user: row.acknowledged_by ?? '' })}
          </span>
        ) : (
          <button
            type="button"
            onClick={() => acknowledge.mutate(row.id)}
            className="text-xs text-brand hover:underline"
          >
            {t('alerts.acknowledge')}
          </button>
        ),
    },
  ]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-body">{t('nav.alerts')}</h1>
          <p className="mt-1 text-sm text-muted">{t('alerts.subtitle')}</p>
        </div>
        {canEdit && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => test.mutate()}
              disabled={test.isPending}
              className="rounded border border-subtle px-2.5 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
            >
              {t('alerts.testNotification')}
            </button>
            <button
              type="button"
              onClick={() => setCreating((value) => !value)}
              className="rounded border border-subtle px-2.5 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
            >
              {creating ? t('common.cancel') : t('alerts.newRule')}
            </button>
          </div>
        )}
      </div>

      {rules.data && !rules.data.notifications_configured && (
        <Banner tone="info" title={t('alerts.noSinksTitle')}>
          {t('alerts.noSinksBody')}
        </Banner>
      )}

      {testResult && <Banner tone="info" title={t('alerts.testResult')}>{testResult}</Banner>}

      {meta.read_only && (
        <Banner tone="info" title={t('banner.readOnlyTitle')}>
          {t('alerts.readOnlyNote')}
        </Banner>
      )}

      {creating && clusters.length > 0 && <NewRuleForm onDone={() => setCreating(false)} />}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-body">{t('alerts.rules')}</h2>
        {rules.isPending ? (
          <TableSkeleton rows={3} />
        ) : (
          <DataTable
            rows={rules.data?.rules ?? []}
            columns={ruleColumns}
            getRowKey={(row) => String(row.id)}
            initialSortKey="state"
            emptyState={<EmptyState title={t('alerts.noRules')} body={t('alerts.noRulesHelp')} />}
          />
        )}
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-body">{t('alerts.notificationCentre')}</h2>
          {(firings.data?.unacknowledged ?? 0) > 0 && (
            <StatusPill
              tone="warn"
              label={t('alerts.unacknowledged', { count: firings.data?.unacknowledged ?? 0 })}
            />
          )}
        </div>
        {firings.isPending ? (
          <TableSkeleton rows={4} />
        ) : (
          <DataTable
            rows={firings.data?.firings ?? []}
            columns={firingColumns}
            getRowKey={(row) => String(row.id)}
            initialSortKey="at"
            emptyState={
              <EmptyState icon="✓" title={t('alerts.quiet')} body={t('alerts.quietHelp')} />
            }
          />
        )}
      </section>

      <ConfirmDialog
        open={toDelete !== null}
        title={t('alerts.deleteRuleTitle')}
        body={t('alerts.deleteRuleBody', { name: toDelete?.name ?? '' })}
        confirmPhrase={toDelete?.name ?? ''}
        confirmLabel={t('alerts.delete')}
        busy={remove.isPending}
        onCancel={() => setToDelete(null)}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
      />
    </div>
  )
}
