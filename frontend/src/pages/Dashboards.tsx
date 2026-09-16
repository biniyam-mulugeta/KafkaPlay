import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import {
  ApiError,
  api,
  type DashboardModel,
  type PanelResult,
  type PanelSpec,
  type PanelType,
  type StatOp,
} from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { formatNumber } from '@/lib/format'
import { Banner } from '@/components/states/Banner'
import { ConfirmDialog } from '@/components/states/ConfirmDialog'
import { EmptyState, Skeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'
import { PanelChart } from '@/components/charts/PanelChart'

const PANEL_TYPES: PanelType[] = ['throughput', 'split_by', 'histogram', 'top_n', 'stat']
const STAT_OPS: StatOp[] = ['count', 'sum', 'avg', 'min', 'max', 'p95']

function newPanel(topic: string): PanelSpec {
  return {
    id: crypto.randomUUID(),
    title: 'New panel',
    type: 'throughput',
    topic,
    extract: null,
    filter: null,
    window_minutes: 60,
    max_messages: 5000,
    top_n: 10,
    buckets: 20,
    thresholds: [],
    stat_op: 'count',
    unit: null,
    persist: false,
    retention_days: 7,
  }
}

function PanelEditor({
  panel,
  topics,
  onChange,
  onRemove,
}: {
  panel: PanelSpec
  topics: string[]
  onChange: (next: PanelSpec) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const set = (patch: Partial<PanelSpec>) => onChange({ ...panel, ...patch })

  return (
    <div className="space-y-2 rounded border border-subtle bg-surface-sunken p-3">
      <div className="flex flex-wrap items-end gap-2">
        <input
          aria-label={t('dashboards.panelTitle')}
          value={panel.title}
          onChange={(event) => set({ title: event.target.value })}
          className="w-40 rounded border border-subtle bg-surface px-2 py-1 text-sm"
        />
        <select
          aria-label={t('dashboards.panelType')}
          value={panel.type}
          onChange={(event) => set({ type: event.target.value as PanelType })}
          className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
        >
          {PANEL_TYPES.map((type) => (
            <option key={type} value={type}>
              {t(`dashboards.type.${type}`)}
            </option>
          ))}
        </select>
        <select
          aria-label={t('topics.name')}
          value={panel.topic}
          onChange={(event) => set({ topic: event.target.value })}
          className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
        >
          {topics.map((topic) => (
            <option key={topic} value={topic}>
              {topic}
            </option>
          ))}
        </select>
        {panel.type === 'stat' && (
          <select
            aria-label={t('dashboards.statOp')}
            value={panel.stat_op}
            onChange={(event) => set({ stat_op: event.target.value as StatOp })}
            className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
          >
            {STAT_OPS.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          onClick={onRemove}
          className="ml-auto text-xs text-critical hover:underline"
        >
          {t('dashboards.removePanel')}
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <input
          aria-label={t('dashboards.extract')}
          value={panel.extract ?? ''}
          onChange={(event) => set({ extract: event.target.value || null })}
          placeholder={t('dashboards.extractPlaceholder')}
          className="min-w-56 flex-1 rounded border border-subtle bg-surface px-2 py-1 font-mono text-xs"
        />
        <input
          aria-label={t('messages.filter')}
          value={panel.filter ?? ''}
          onChange={(event) => set({ filter: event.target.value || null })}
          placeholder={t('dashboards.filterPlaceholder')}
          className="min-w-56 flex-1 rounded border border-subtle bg-surface px-2 py-1 font-mono text-xs"
        />
        {panel.type === 'histogram' && (
          <input
            aria-label={t('dashboards.thresholds')}
            value={panel.thresholds.join(',')}
            onChange={(event) =>
              set({
                thresholds: event.target.value
                  .split(',')
                  .map((part) => Number(part.trim()))
                  .filter((value) => !Number.isNaN(value)),
              })
            }
            placeholder={t('dashboards.thresholdsPlaceholder')}
            className="w-32 rounded border border-subtle bg-surface px-2 py-1 font-mono text-xs"
          />
        )}
      </div>
    </div>
  )
}

export function Dashboards() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<{ name: string; panels: PanelSpec[] }>({
    name: '',
    panels: [],
  })
  const [results, setResults] = useState<PanelResult[]>([])
  const [error, setError] = useState<string | null>(null)
  const [toDelete, setToDelete] = useState<DashboardModel | null>(null)

  const dashboards = useQuery({
    queryKey: ['dashboards', cluster],
    queryFn: () => api.dashboards(cluster!),
    enabled: Boolean(cluster),
    refetchInterval: false,
  })

  const topics = useQuery({
    queryKey: ['topics', cluster, false],
    queryFn: () => api.topics(cluster!, false),
    enabled: Boolean(cluster),
    refetchInterval: false,
  })

  // Derived rather than stored: selectedId is an explicit override, and the
  // first dashboard is the default, so the page is never blank when one
  // exists and no effect has to reach back and set state.
  const selected = useMemo(() => {
    const all = dashboards.data?.dashboards ?? []
    if (all.length === 0) return null
    return all.find((item) => item.id === selectedId) ?? all[0] ?? null
  }, [dashboards.data, selectedId])

  const render = useMutation({
    mutationFn: (panels: PanelSpec[]) => api.renderPanels(cluster!, panels),
    onSuccess: setResults,
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  // Rendering is a scan, so it runs on demand rather than on a poll.
  useEffect(() => {
    if (selected && selected.panels.length > 0 && !editing) {
      render.mutate(selected.panels)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, editing])

  const save = useMutation({
    mutationFn: () =>
      selected
        ? api.updateDashboard(cluster!, selected.id, {
            name: draft.name,
            panels: draft.panels,
          })
        : api.createDashboard(cluster!, { name: draft.name, panels: draft.panels }),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ['dashboards', cluster] })
      setSelectedId(saved.id)
      setEditing(false)
      setError(null)
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteDashboard(cluster!, id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['dashboards', cluster] })
      setSelectedId(null)
      setToDelete(null)
    },
  })

  function startEdit(source: DashboardModel | null) {
    setDraft({
      name: source?.name ?? 'New dashboard',
      panels: source?.panels ?? [newPanel(topics.data?.topics[0]?.name ?? '')],
    })
    setEditing(true)
  }

  function exportDashboard() {
    if (!selected) return
    const blob = new Blob(
      [JSON.stringify({ name: selected.name, panels: selected.panels }, null, 2)],
      { type: 'application/json' },
    )
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selected.name.replace(/\W+/g, '-').toLowerCase()}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  function importDashboard(file: File) {
    void file.text().then((text) => {
      try {
        const parsed = JSON.parse(text)
        setDraft({ name: parsed.name ?? 'Imported', panels: parsed.panels ?? [] })
        setSelectedId(null)
        setEditing(true)
        setError(null)
      } catch {
        setError(t('dashboards.importFailed'))
      }
    })
  }

  if (!cluster) return <NoCluster />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-body">{t('nav.dashboards')}</h1>
          <p className="mt-1 text-sm text-muted">{t('dashboards.subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            aria-label={t('nav.dashboards')}
            value={selectedId ?? ''}
            onChange={(event) => {
              setSelectedId(Number(event.target.value) || null)
              setEditing(false)
            }}
            className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
          >
            <option value="">{t('dashboards.select')}</option>
            {(dashboards.data?.dashboards ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => startEdit(null)}
            className="rounded border border-subtle px-2.5 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
          >
            {t('dashboards.new')}
          </button>
          {selected && !editing && (
            <>
              <button
                type="button"
                onClick={() => startEdit(selected)}
                className="rounded border border-subtle px-2.5 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
              >
                {t('dashboards.edit')}
              </button>
              <button
                type="button"
                onClick={exportDashboard}
                className="rounded border border-subtle px-2.5 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
              >
                {t('dashboards.export')}
              </button>
              <button
                type="button"
                onClick={() => setToDelete(selected)}
                className="rounded border border-subtle px-2.5 py-1 text-xs text-critical hover:bg-critical-tint"
              >
                {t('dashboards.delete')}
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="rounded border border-subtle px-2.5 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
          >
            {t('dashboards.import')}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) importDashboard(file)
              event.target.value = ''
            }}
          />
        </div>
      </div>

      {error && <Banner tone="critical" title={t('errors.genericTitle')}>{error}</Banner>}

      {editing ? (
        <div className="space-y-3 rounded-lg border border-subtle bg-surface p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="dash-name" className="block text-xs font-medium text-muted">
                {t('dashboards.name')}
              </label>
              <input
                id="dash-name"
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                className="mt-1 rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
              />
            </div>
            <button
              type="button"
              onClick={() =>
                setDraft({
                  ...draft,
                  panels: [...draft.panels, newPanel(topics.data?.topics[0]?.name ?? '')],
                })
              }
              className="rounded border border-subtle px-2.5 py-1.5 text-xs text-muted hover:bg-surface-sunken hover:text-body"
            >
              {t('dashboards.addPanel')}
            </button>
            <div className="flex-1" />
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded border border-subtle px-3 py-1.5 text-sm text-muted hover:bg-surface-sunken"
            >
              {t('common.cancel')}
            </button>
            <button
              type="button"
              disabled={!draft.name || save.isPending}
              onClick={() => save.mutate()}
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-50"
            >
              {t('common.save')}
            </button>
          </div>

          <div className="space-y-2">
            {draft.panels.map((panel, index) => (
              <PanelEditor
                key={panel.id}
                panel={panel}
                topics={(topics.data?.topics ?? []).map((item) => item.name)}
                onChange={(next) => {
                  const panels = [...draft.panels]
                  panels[index] = next
                  setDraft({ ...draft, panels })
                }}
                onRemove={() =>
                  setDraft({
                    ...draft,
                    panels: draft.panels.filter((item) => item.id !== panel.id),
                  })
                }
              />
            ))}
          </div>
        </div>
      ) : !selected ? (
        <EmptyState
          title={t('dashboards.none')}
          body={t('dashboards.noneHelp')}
          action={
            <button
              type="button"
              onClick={() => startEdit(null)}
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover"
            >
              {t('dashboards.new')}
            </button>
          }
        />
      ) : (
        <>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => render.mutate(selected.panels)}
              disabled={render.isPending}
              className="rounded border border-brand px-2.5 py-1 text-xs font-medium text-brand hover:bg-brand-tint disabled:opacity-50"
            >
              {render.isPending ? t('dashboards.rendering') : t('dashboards.refresh')}
            </button>
            <span className="text-[11px] text-faint">{t('dashboards.onDemandHint')}</span>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            {selected.panels.map((panel) => {
              const result = results.find((item) => item.id === panel.id)
              return (
                <div key={panel.id} className="rounded-lg border border-subtle bg-surface p-3">
                  <div className="mb-2 flex items-baseline justify-between gap-2">
                    <h2 className="text-sm font-medium text-body">{panel.title}</h2>
                    <span className="font-mono text-[10px] text-faint">{panel.topic}</span>
                  </div>
                  {render.isPending ? (
                    <Skeleton className="h-40 w-full" />
                  ) : result ? (
                    <>
                      <PanelChart result={result} />
                      <p className="mt-1 text-[10px] text-faint">
                        {t('dashboards.panelFooter', {
                          matched: formatNumber(result.matched),
                          sampled: formatNumber(result.sampled),
                          seconds: result.elapsed_seconds,
                        })}
                      </p>
                    </>
                  ) : (
                    <p className="py-8 text-center text-xs text-muted">
                      {t('dashboards.notRendered')}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}

      <ConfirmDialog
        open={toDelete !== null}
        title={t('dashboards.deleteTitle')}
        body={t('dashboards.deleteBody', { name: toDelete?.name ?? '' })}
        confirmPhrase={toDelete?.name ?? ''}
        confirmLabel={t('dashboards.delete')}
        busy={remove.isPending}
        onCancel={() => setToDelete(null)}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
      />
    </div>
  )
}
