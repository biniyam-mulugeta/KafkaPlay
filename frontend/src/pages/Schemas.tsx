import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, api } from '@/lib/api'
import { useClusterName } from '@/lib/cluster'
import { Banner } from '@/components/states/Banner'
import { EmptyState, Skeleton, TableSkeleton } from '@/components/states/EmptyState'
import { NoCluster } from '@/components/states/NoCluster'
import { StatusPill } from '@/components/states/StatusPill'

function DiffView({ unified }: { unified: string }) {
  const { t } = useTranslation()
  if (!unified.trim()) {
    return <p className="py-6 text-center text-xs text-muted">{t('schemas.identical')}</p>
  }

  return (
    <pre className="max-h-96 overflow-auto rounded border border-subtle bg-surface-sunken p-3 font-mono text-[11px] leading-relaxed">
      {unified.split('\n').map((line, index) => {
        // Colour by diff marker, but also keep the marker itself, so the
        // diff is readable without relying on colour.
        const tone = line.startsWith('+')
          ? 'text-ok'
          : line.startsWith('-')
            ? 'text-critical'
            : line.startsWith('@@')
              ? 'text-info'
              : 'text-muted'
        return (
          <div key={index} className={tone}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}

export function Schemas() {
  const { t } = useTranslation()
  const cluster = useClusterName()
  const [subject, setSubject] = useState<string | null>(null)
  const [fromVersion, setFromVersion] = useState<number | null>(null)
  const [toVersion, setToVersion] = useState<number | null>(null)

  const subjects = useQuery({
    queryKey: ['subjects', cluster],
    queryFn: () => api.subjects(cluster!),
    enabled: Boolean(cluster),
    retry: false,
    refetchInterval: false,
  })

  const detail = useQuery({
    queryKey: ['subject', cluster, subject],
    queryFn: () => api.subject(cluster!, subject!),
    enabled: Boolean(cluster && subject),
    refetchInterval: false,
  })

  const latest = useQuery({
    queryKey: ['schema', cluster, subject, 'latest'],
    queryFn: () => api.schemaVersion(cluster!, subject!, 'latest'),
    enabled: Boolean(cluster && subject),
    refetchInterval: false,
  })

  const diff = useQuery({
    queryKey: ['schema-diff', cluster, subject, fromVersion, toVersion],
    queryFn: () => api.schemaDiff(cluster!, subject!, fromVersion!, toVersion!),
    enabled: Boolean(cluster && subject && fromVersion && toVersion),
    refetchInterval: false,
  })

  if (!cluster) return <NoCluster />

  // A missing registry is a configuration state, not an error page.
  if (subjects.isError) {
    const error = subjects.error
    const notConfigured = error instanceof ApiError && error.status === 501
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold text-body">{t('nav.schemas')}</h1>
        <EmptyState
          icon={notConfigured ? '◇' : '▲'}
          title={notConfigured ? t('schemas.notConfigured') : t('errors.genericTitle')}
          body={error instanceof ApiError ? error.message : t('errors.genericBody')}
        />
      </div>
    )
  }

  const versions = detail.data?.versions ?? []

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-body">{t('nav.schemas')}</h1>
        <p className="mt-1 text-sm text-muted">{t('schemas.subtitle')}</p>
      </div>

      {subjects.isPending ? (
        <TableSkeleton rows={5} />
      ) : (subjects.data?.subjects ?? []).length === 0 ? (
        <EmptyState title={t('schemas.noSubjects')} body={t('schemas.noSubjectsHelp')} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
          <nav aria-label={t('schemas.subjects')} className="space-y-1">
            {(subjects.data?.subjects ?? []).map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => {
                  setSubject(name)
                  setFromVersion(null)
                  setToVersion(null)
                }}
                className={`block w-full truncate rounded px-2 py-1.5 text-left font-mono text-xs ${
                  subject === name
                    ? 'bg-brand-tint font-medium text-brand'
                    : 'text-muted hover:bg-surface-sunken hover:text-body'
                }`}
              >
                {name}
              </button>
            ))}
          </nav>

          <div className="space-y-4">
            {!subject ? (
              <EmptyState title={t('schemas.pickSubject')} />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-3 rounded-lg border border-subtle bg-surface p-3">
                  <span className="font-mono text-sm text-body">{subject}</span>
                  {detail.data?.compatibility && (
                    <StatusPill tone="neutral" label={detail.data.compatibility} />
                  )}
                  {latest.data && (
                    <span className="text-xs text-muted">
                      {t('schemas.type')}: {latest.data.schema_type} ·{' '}
                      {t('schemas.id')}: {latest.data.id}
                    </span>
                  )}
                  <span className="text-xs text-muted">
                    {t('schemas.versionCount', { count: versions.length })}
                  </span>
                </div>

                <section className="space-y-2">
                  <h2 className="text-sm font-semibold text-body">{t('schemas.latest')}</h2>
                  {latest.isPending ? (
                    <Skeleton className="h-48 w-full" />
                  ) : (
                    <pre className="max-h-80 overflow-auto rounded border border-subtle bg-surface-sunken p-3 font-mono text-[11px]">
                      {(() => {
                        try {
                          return JSON.stringify(
                            JSON.parse(latest.data?.schema_text ?? '{}'),
                            null,
                            2,
                          )
                        } catch {
                          // Protobuf schemas are plain text, not JSON.
                          return latest.data?.schema_text ?? ''
                        }
                      })()}
                    </pre>
                  )}
                </section>

                {versions.length > 1 && (
                  <section className="space-y-2">
                    <h2 className="text-sm font-semibold text-body">{t('schemas.compare')}</h2>
                    <div className="flex flex-wrap items-center gap-2">
                      <label htmlFor="from-v" className="text-xs text-muted">
                        {t('schemas.from')}
                      </label>
                      <select
                        id="from-v"
                        value={fromVersion ?? ''}
                        onChange={(event) => setFromVersion(Number(event.target.value) || null)}
                        className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
                      >
                        <option value="">—</option>
                        {versions.map((version) => (
                          <option key={version} value={version}>
                            v{version}
                          </option>
                        ))}
                      </select>
                      <label htmlFor="to-v" className="text-xs text-muted">
                        {t('schemas.to')}
                      </label>
                      <select
                        id="to-v"
                        value={toVersion ?? ''}
                        onChange={(event) => setToVersion(Number(event.target.value) || null)}
                        className="rounded border border-subtle bg-surface px-2 py-1 text-xs"
                      >
                        <option value="">—</option>
                        {versions.map((version) => (
                          <option key={version} value={version}>
                            v{version}
                          </option>
                        ))}
                      </select>
                      {diff.data && (
                        <span className="text-xs text-muted">
                          <span className="text-ok">+{diff.data.added}</span>{' '}
                          <span className="text-critical">−{diff.data.removed}</span>
                        </span>
                      )}
                    </div>

                    {diff.isPending && fromVersion && toVersion ? (
                      <Skeleton className="h-48 w-full" />
                    ) : diff.data ? (
                      <DiffView unified={diff.data.unified} />
                    ) : (
                      <p className="text-xs text-muted">{t('schemas.pickVersions')}</p>
                    )}
                  </section>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export function Acls() {
  const { t } = useTranslation()
  const cluster = useClusterName()

  const acls = useQuery({
    queryKey: ['acls', cluster],
    queryFn: () => api.acls(cluster!),
    enabled: Boolean(cluster),
    refetchInterval: false,
  })

  if (!cluster) return <NoCluster />

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-body">{t('nav.acls')}</h1>
        <p className="mt-1 text-sm text-muted">{t('acls.subtitle')}</p>
      </div>

      {acls.data && !acls.data.supported && (
        <Banner tone="info" title={t('acls.notAvailable')}>
          {acls.data.message}
        </Banner>
      )}

      {acls.isPending ? (
        <TableSkeleton rows={5} />
      ) : (acls.data?.acls ?? []).length === 0 ? (
        acls.data?.supported ? (
          <EmptyState title={t('acls.none')} body={t('acls.noneHelp')} />
        ) : null
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle bg-surface">
          <table className="w-full text-sm">
            <thead className="border-b border-subtle bg-surface-sunken">
              <tr>
                {['principal', 'resource', 'pattern', 'operation', 'permission', 'host'].map(
                  (key) => (
                    <th
                      key={key}
                      scope="col"
                      className="px-3 py-2 text-left text-xs font-medium text-muted"
                    >
                      {t(`acls.${key}`)}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {(acls.data?.acls ?? []).map((acl, index) => (
                <tr key={index} className="border-b border-subtle last:border-0">
                  <td className="px-3 py-1.5 font-mono text-xs">{acl.principal}</td>
                  <td className="px-3 py-1.5 font-mono text-xs">
                    {acl.resource_type}:{acl.resource_name}
                  </td>
                  <td className="px-3 py-1.5 text-xs text-muted">{acl.pattern_type}</td>
                  <td className="px-3 py-1.5 text-xs">{acl.operation}</td>
                  <td className="px-3 py-1.5">
                    <StatusPill
                      tone={acl.permission === 'ALLOW' ? 'ok' : 'critical'}
                      label={acl.permission}
                    />
                  </td>
                  <td className="px-3 py-1.5 font-mono text-xs text-muted">{acl.host}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
