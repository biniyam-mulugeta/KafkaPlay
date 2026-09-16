import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, api, type AppUser, type Role } from '@/lib/api'
import { formatTimestamp } from '@/lib/format'
import { Banner } from '@/components/states/Banner'
import { ConfirmDialog } from '@/components/states/ConfirmDialog'
import { DataTable, type Column } from '@/components/table/DataTable'
import { EmptyState, TableSkeleton } from '@/components/states/EmptyState'
import { StatusPill } from '@/components/states/StatusPill'
import { useSession } from '@/lib/session'
import { AddClusterForm } from '@/components/admin/AddClusterForm'
import { useCluster } from '@/lib/cluster'

const ROLES: Role[] = ['viewer', 'operator', 'admin']

function ChangeOwnPassword() {
  const { t } = useTranslation()
  const { me } = useSession()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () =>
      api.changePassword(me!.username, { current_password: current, new_password: next }),
    onSuccess: () => {
      setDone(true)
      setCurrent('')
      setNext('')
      setError(null)
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  if (!me || me.provider !== 'local') return null

  return (
    <section className="space-y-3 rounded-lg border border-subtle bg-surface p-4">
      <h2 className="text-sm font-semibold text-body">{t('settings.changePassword')}</h2>

      {done && <Banner tone="ok" title={t('settings.passwordChanged')} />}
      {error && <Banner tone="critical" title={t('errors.genericTitle')}>{error}</Banner>}

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="current-pw" className="block text-xs font-medium text-muted">
            {t('settings.currentPassword')}
          </label>
          <input
            id="current-pw"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            className="mt-1 rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label htmlFor="new-pw" className="block text-xs font-medium text-muted">
            {t('settings.newPassword')}
          </label>
          <input
            id="new-pw"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
            className="mt-1 rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
          />
        </div>
        <button
          type="button"
          disabled={next.length < 12 || mutation.isPending}
          onClick={() => mutation.mutate()}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-50"
        >
          {t('common.save')}
        </button>
      </div>
      <p className="text-[11px] text-faint">{t('settings.passwordRule')}</p>
    </section>
  )
}

function UserAdmin() {
  const { t } = useTranslation()
  const { me } = useSession()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>('viewer')
  const [error, setError] = useState<string | null>(null)
  const [toDelete, setToDelete] = useState<AppUser | null>(null)

  const users = useQuery({ queryKey: ['users'], queryFn: api.users, refetchInterval: false })

  function handleError(caught: unknown) {
    setError(caught instanceof ApiError ? caught.message : String(caught))
  }

  const create = useMutation({
    mutationFn: () => api.createUser({ username, password, role }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      setCreating(false)
      setUsername('')
      setPassword('')
      setError(null)
    },
    onError: handleError,
  })

  const update = useMutation({
    mutationFn: (input: { username: string; role?: Role; is_active?: boolean }) =>
      api.updateUser(input.username, { role: input.role, is_active: input.is_active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['users'] }),
    onError: handleError,
  })

  const remove = useMutation({
    mutationFn: (name: string) => api.deleteUser(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      setToDelete(null)
      setError(null)
    },
    onError: handleError,
  })

  const columns: Column<AppUser>[] = [
    {
      key: 'username',
      header: t('common.username'),
      sortValue: (row) => row.username,
      render: (row) => (
        <span className="text-sm">
          {row.username}
          {row.username === me?.username && (
            <span className="ml-1.5 text-[10px] text-faint">{t('settings.you')}</span>
          )}
        </span>
      ),
    },
    {
      key: 'role',
      header: t('settings.role'),
      sortValue: (row) => row.role,
      render: (row) => (
        <select
          value={row.role}
          aria-label={t('settings.roleFor', { username: row.username })}
          // An admin demoting themselves would lock the deployment out; the
          // backend refuses it too, this just avoids offering it.
          disabled={row.username === me?.username}
          onChange={(event) =>
            update.mutate({ username: row.username, role: event.target.value as Role })
          }
          className="rounded border border-subtle bg-surface px-2 py-1 text-xs disabled:opacity-50"
        >
          {ROLES.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ),
    },
    {
      key: 'status',
      header: t('settings.status'),
      render: (row) =>
        row.is_active ? (
          <StatusPill tone="ok" label={t('settings.active')} />
        ) : (
          <StatusPill tone="warn" label={t('settings.disabled')} />
        ),
    },
    {
      key: 'lastLogin',
      header: t('settings.lastLogin'),
      sortValue: (row) => row.last_login_at,
      render: (row) => (
        <span className="text-xs text-muted">
          {row.last_login_at ? formatTimestamp(row.last_login_at) : '—'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (row) =>
        row.username === me?.username ? null : (
          <button
            type="button"
            onClick={() => setToDelete(row)}
            className="text-xs text-critical hover:underline"
          >
            {t('settings.deleteUser')}
          </button>
        ),
    },
  ]

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-body">{t('settings.users')}</h2>
        <button
          type="button"
          onClick={() => setCreating((value) => !value)}
          className="rounded border border-subtle px-2.5 py-1 text-xs text-muted hover:bg-surface-sunken hover:text-body"
        >
          {creating ? t('common.cancel') : t('settings.addUser')}
        </button>
      </div>

      {error && <Banner tone="critical" title={t('errors.genericTitle')}>{error}</Banner>}

      {creating && (
        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-subtle bg-surface p-4">
          <div>
            <label htmlFor="new-username" className="block text-xs font-medium text-muted">
              {t('common.username')}
            </label>
            <input
              id="new-username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="mt-1 rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="new-password" className="block text-xs font-medium text-muted">
              {t('common.password')}
            </label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="new-role" className="block text-xs font-medium text-muted">
              {t('settings.role')}
            </label>
            <select
              id="new-role"
              value={role}
              onChange={(event) => setRole(event.target.value as Role)}
              className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
            >
              {ROLES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            disabled={!username || password.length < 12 || create.isPending}
            onClick={() => create.mutate()}
            className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-50"
          >
            {t('settings.addUser')}
          </button>
        </div>
      )}

      {users.isPending ? (
        <TableSkeleton rows={3} />
      ) : (
        <DataTable
          rows={users.data?.users ?? []}
          columns={columns}
          getRowKey={(row) => row.username}
          initialSortKey="username"
          emptyState={<EmptyState title={t('settings.noUsers')} />}
        />
      )}

      <ConfirmDialog
        open={toDelete !== null}
        title={t('settings.deleteUserTitle')}
        body={t('settings.deleteUserBody', { username: toDelete?.username ?? '' })}
        confirmPhrase={toDelete?.username ?? ''}
        confirmLabel={t('settings.deleteUser')}
        busy={remove.isPending}
        onCancel={() => setToDelete(null)}
        onConfirm={() => toDelete && remove.mutate(toDelete.username)}
      />
    </section>
  )
}

function ClusterList() {
  const { t } = useTranslation()
  const { clusters } = useCluster()
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const remove = useMutation({
    mutationFn: (name: string) => api.removeCluster(name),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['clusters'] }),
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  if (clusters.length === 0) return null

  return (
    <div className="space-y-2">
      {error && <Banner tone="warn" title={t('errors.genericTitle')}>{error}</Banner>}
      <ul className="divide-y divide-subtle rounded-lg border border-subtle bg-surface">
        {clusters.map((cluster) => (
          <li key={cluster.name} className="flex items-center gap-3 px-3 py-2">
            <span className="text-sm text-body">{cluster.label}</span>
            <span className="font-mono text-[11px] text-faint">{cluster.security_protocol}</span>
            {cluster.read_only && (
              <span className="rounded border border-warn px-1.5 py-0.5 text-[10px] text-warn">
                {t('clusters.readOnly')}
              </span>
            )}
            <div className="flex-1" />
            <button
              type="button"
              onClick={() => remove.mutate(cluster.name)}
              className="text-xs text-critical hover:underline"
            >
              {t('addCluster.remove')}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Settings() {
  const { t } = useTranslation()
  const { meta, me } = useSession()

  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold text-body">{t('nav.settings')}</h1>

      <section className="space-y-2 rounded-lg border border-subtle bg-surface p-4">
        <h2 className="text-sm font-semibold text-body">{t('settings.deployment')}</h2>
        <dl className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-muted">{t('settings.version')}</dt>
            <dd className="tabular">{meta.version}</dd>
          </div>
          <div>
            <dt className="text-muted">{t('settings.authMode')}</dt>
            <dd>{meta.auth_mode}</dd>
          </div>
          <div>
            <dt className="text-muted">{t('settings.readOnly')}</dt>
            <dd>{meta.read_only ? t('common.yes') : t('common.no')}</dd>
          </div>
          <div>
            <dt className="text-muted">{t('settings.masking')}</dt>
            <dd>{meta.masking_enabled ? t('common.yes') : t('common.no')}</dd>
          </div>
        </dl>
        <p className="text-[11px] text-faint">{t('settings.configHint')}</p>
      </section>

      {me?.role === 'admin' && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-body">{t('addCluster.yours')}</h2>
          <ClusterList />
          <AddClusterForm />
        </section>
      )}

      <ChangeOwnPassword />

      {me?.role === 'admin' && meta.auth_mode !== 'none' && <UserAdmin />}
    </div>
  )
}
