import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, api } from '@/lib/api'
import { Banner } from '@/components/states/Banner'

const PROTOCOLS = ['PLAINTEXT', 'SSL', 'SASL_PLAINTEXT', 'SASL_SSL'] as const
const MECHANISMS = ['PLAIN', 'SCRAM-SHA-256', 'SCRAM-SHA-512'] as const

/**
 * Adds a cluster without editing a file.
 *
 * The connection is tested before it can be saved, so a typo in a broker
 * address or a wrong SASL mechanism is caught here rather than showing up as
 * an empty topic list later.
 */
export function AddClusterForm({ onAdded }: { onAdded?: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [bootstrap, setBootstrap] = useState('')
  const [protocol, setProtocol] = useState<(typeof PROTOCOLS)[number]>('PLAINTEXT')
  const [mechanism, setMechanism] = useState<(typeof MECHANISMS)[number]>('SCRAM-SHA-512')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [registryUrl, setRegistryUrl] = useState('')
  const [readOnly, setReadOnly] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const usesSasl = protocol.startsWith('SASL')

  function body() {
    return {
      name,
      bootstrap_servers: bootstrap,
      security_protocol: protocol,
      sasl_mechanism: usesSasl ? mechanism : null,
      sasl_username: usesSasl ? username : null,
      sasl_password: usesSasl ? password : null,
      schema_registry_url: registryUrl || null,
      read_only: readOnly,
    }
  }

  const test = useMutation({
    mutationFn: () => api.testCluster(body()),
    onSuccess: () => setError(null),
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  const add = useMutation({
    mutationFn: () => api.addCluster(body()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['clusters'] })
      setError(null)
      onAdded?.()
      // A new cluster changes what the whole app can show, so reload rather
      // than trying to reconcile every cached query.
      window.location.reload()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  const result = test.data
  const ready = Boolean(name && bootstrap)

  return (
    <div className="space-y-3 rounded-lg border border-subtle bg-surface p-4">
      <h2 className="text-sm font-semibold text-body">{t('addCluster.title')}</h2>

      {error && <Banner tone="critical" title={t('errors.genericTitle')}>{error}</Banner>}

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="cl-name" className="block text-xs font-medium text-muted">
            {t('addCluster.name')}
          </label>
          <input
            id="cl-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="production"
            className="mt-1 w-40 rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
          />
        </div>

        <div className="min-w-64 flex-1">
          <label htmlFor="cl-bootstrap" className="block text-xs font-medium text-muted">
            {t('addCluster.bootstrap')}
          </label>
          <input
            id="cl-bootstrap"
            value={bootstrap}
            onChange={(event) => setBootstrap(event.target.value)}
            placeholder="broker-1:9092,broker-2:9092"
            className="mt-1 w-full rounded border border-subtle bg-surface px-3 py-1.5 font-mono text-sm"
          />
        </div>

        <div>
          <label htmlFor="cl-protocol" className="block text-xs font-medium text-muted">
            {t('addCluster.security')}
          </label>
          <select
            id="cl-protocol"
            value={protocol}
            onChange={(event) => setProtocol(event.target.value as typeof protocol)}
            className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
          >
            {PROTOCOLS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </div>

      {usesSasl && (
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="cl-mech" className="block text-xs font-medium text-muted">
              {t('addCluster.mechanism')}
            </label>
            <select
              id="cl-mech"
              value={mechanism}
              onChange={(event) => setMechanism(event.target.value as typeof mechanism)}
              className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
            >
              {MECHANISMS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cl-user" className="block text-xs font-medium text-muted">
              {t('common.username')}
            </label>
            <input
              id="cl-user"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="mt-1 rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="cl-pass" className="block text-xs font-medium text-muted">
              {t('common.password')}
            </label>
            <input
              id="cl-pass"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 rounded border border-subtle bg-surface px-3 py-1.5 text-sm"
            />
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-64 flex-1">
          <label htmlFor="cl-registry" className="block text-xs font-medium text-muted">
            {t('addCluster.registry')}
          </label>
          <input
            id="cl-registry"
            value={registryUrl}
            onChange={(event) => setRegistryUrl(event.target.value)}
            placeholder="http://schema-registry:8081"
            className="mt-1 w-full rounded border border-subtle bg-surface px-3 py-1.5 font-mono text-sm"
          />
        </div>
        <label className="flex items-center gap-2 pb-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={readOnly}
            onChange={(event) => setReadOnly(event.target.checked)}
          />
          {t('addCluster.readOnly')}
        </label>
      </div>

      {result && (
        <Banner
          tone={result.ok ? 'ok' : 'critical'}
          title={result.ok ? t('addCluster.reachable') : t('addCluster.unreachable')}
        >
          {result.ok
            ? t('addCluster.reachableDetail', {
                brokers: result.brokers,
                topics: result.topics,
              })
            : result.error}
        </Banner>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!ready || test.isPending}
          onClick={() => test.mutate()}
          className="rounded border border-brand px-3 py-1.5 text-sm font-medium text-brand hover:bg-brand-tint disabled:opacity-50"
        >
          {test.isPending ? t('addCluster.testing') : t('addCluster.test')}
        </button>
        <button
          type="button"
          // Saving is gated on a successful test: a cluster that cannot be
          // reached is not worth storing.
          disabled={!ready || !result?.ok || add.isPending}
          onClick={() => add.mutate()}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-brand-contrast hover:bg-brand-hover disabled:opacity-50"
        >
          {add.isPending ? t('addCluster.adding') : t('addCluster.add')}
        </button>
        {!result?.ok && ready && (
          <span className="self-center text-[11px] text-faint">{t('addCluster.testFirst')}</span>
        )}
      </div>
    </div>
  )
}
