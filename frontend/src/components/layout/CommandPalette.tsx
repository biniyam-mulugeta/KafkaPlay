import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api } from '@/lib/api'
import { useCluster, useClusterName } from '@/lib/cluster'

interface Command {
  id: string
  label: string
  hint: string
  run: () => void
}

/** Case-insensitive subsequence match, so "cgr" finds "Consumer Groups". */
function matches(haystack: string, needle: string): boolean {
  if (!needle) return true
  const target = haystack.toLowerCase()
  const query = needle.toLowerCase()
  let index = 0
  for (const character of query) {
    index = target.indexOf(character, index)
    if (index === -1) return false
    index += 1
  }
  return true
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const cluster = useClusterName()
  const { clusters, setCurrent } = useCluster()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  // Only fetched while the palette is open, so it costs nothing otherwise.
  const topics = useQuery({
    queryKey: ['topics', cluster, false],
    queryFn: () => api.topics(cluster!, false),
    enabled: open && Boolean(cluster),
    refetchInterval: false,
  })
  const groups = useQuery({
    queryKey: ['groups', cluster],
    queryFn: () => api.groups(cluster!, false),
    enabled: open && Boolean(cluster),
    refetchInterval: false,
  })

  const commands = useMemo<Command[]>(() => {
    const go = (path: string) => () => {
      navigate(path)
      onClose()
    }

    const pages: Command[] = [
      ['nav.overview', '/'],
      ['nav.topics', '/topics'],
      ['nav.consumerGroups', '/consumer-groups'],
      ['nav.messages', '/messages'],
      ['nav.replication', '/replication'],
      ['nav.metrics', '/metrics'],
      ['nav.dashboards', '/dashboards'],
      ['nav.flowMap', '/flow-map'],
      ['nav.schemas', '/schemas'],
      ['nav.acls', '/acls'],
      ['nav.alerts', '/alerts'],
      ['nav.audit', '/audit'],
      ['nav.settings', '/settings'],
    ].map(([key, path]) => ({
      id: `page:${path}`,
      label: t(key!),
      hint: t('palette.page'),
      run: go(path!),
    }))

    const topicCommands: Command[] = (topics.data?.topics ?? []).map((topic) => ({
      id: `topic:${topic.name}`,
      label: topic.name,
      hint: t('palette.topic'),
      run: go(`/topics/${encodeURIComponent(topic.name)}`),
    }))

    const groupCommands: Command[] = (groups.data?.groups ?? []).map((group) => ({
      id: `group:${group.group_id}`,
      label: group.group_id,
      hint: t('palette.group'),
      run: go(`/consumer-groups/${encodeURIComponent(group.group_id)}`),
    }))

    const clusterCommands: Command[] =
      clusters.length > 1
        ? clusters.map((item) => ({
            id: `cluster:${item.name}`,
            label: item.label,
            hint: t('palette.cluster'),
            run: () => {
              setCurrent(item.name)
              onClose()
            },
          }))
        : []

    return [...pages, ...clusterCommands, ...topicCommands, ...groupCommands]
  }, [t, navigate, onClose, topics.data, groups.data, clusters, setCurrent])

  const filtered = useMemo(
    () => commands.filter((command) => matches(command.label, query)).slice(0, 40),
    [commands, query],
  )

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
      } else if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActive((value) => Math.min(value + 1, filtered.length - 1))
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActive((value) => Math.max(value - 1, 0))
      } else if (event.key === 'Enter') {
        event.preventDefault()
        filtered[active]?.run()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, filtered, active])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-24"
      style={{ background: 'var(--kp-overlay)' }}
      role="dialog"
      aria-modal="true"
      aria-label={t('palette.title')}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-lg border border-subtle bg-surface shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          autoFocus
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setActive(0)
          }}
          placeholder={t('palette.placeholder')}
          aria-label={t('palette.placeholder')}
          className="w-full border-b border-subtle bg-surface px-4 py-3 text-sm outline-none"
        />

        {filtered.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-muted">{t('palette.noMatches')}</p>
        ) : (
          <ul className="max-h-80 overflow-auto py-1">
            {filtered.map((command, index) => (
              <li key={command.id}>
                <button
                  type="button"
                  onMouseEnter={() => setActive(index)}
                  onClick={command.run}
                  aria-current={index === active}
                  className={`flex w-full items-center justify-between gap-3 px-4 py-1.5 text-left text-sm ${
                    index === active ? 'bg-brand-tint text-brand' : 'text-body'
                  }`}
                >
                  <span className="truncate">{command.label}</span>
                  <span className="shrink-0 text-[10px] uppercase text-faint">
                    {command.hint}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-3 border-t border-subtle px-4 py-2 text-[10px] text-faint">
          <span>↑↓ {t('palette.navigate')}</span>
          <span>↵ {t('palette.open')}</span>
          <span>esc {t('common.close')}</span>
        </div>
      </div>
    </div>
  )
}

/** Ctrl/Cmd+K anywhere in the app. */
export function useCommandPalette() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return { open, setOpen }
}
