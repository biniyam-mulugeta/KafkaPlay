import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, api, type OffsetResetResponse, type ResetTo } from '@/lib/api'
import { formatNumber } from '@/lib/format'
import { Banner } from '@/components/states/Banner'
import { ConfirmDialog } from '@/components/states/ConfirmDialog'

/**
 * Offset reset, always preview-then-confirm.
 *
 * The dry run is not optional: the operator sees the exact target offsets and
 * how many records would be skipped or replayed before anything is applied,
 * and the apply step sends back the same preview the backend computed.
 */
export function OffsetResetDialog({
  cluster,
  groupId,
  open,
  onClose,
  onApplied,
}: {
  cluster: string
  groupId: string
  open: boolean
  onClose: () => void
  onApplied: () => void
}) {
  const { t } = useTranslation()
  const [resetTo, setResetTo] = useState<ResetTo>('earliest')
  const [targetOffset, setTargetOffset] = useState('')
  const [timestamp, setTimestamp] = useState('')
  const [shiftBy, setShiftBy] = useState('')
  const [preview, setPreview] = useState<OffsetResetResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  function body() {
    return {
      reset_to: resetTo,
      target_offset: resetTo === 'offset' && targetOffset ? Number(targetOffset) : null,
      timestamp_ms:
        resetTo === 'timestamp' && timestamp ? new Date(timestamp).getTime() : null,
      shift_by: resetTo === 'shift' && shiftBy ? Number(shiftBy) : null,
    }
  }

  const dryRun = useMutation({
    mutationFn: () => api.resetOffsets(cluster, groupId, { ...body(), dry_run: true }),
    onSuccess: (data) => {
      setPreview(data)
      setError(null)
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : String(caught)),
  })

  const apply = useMutation({
    mutationFn: () =>
      api.resetOffsets(cluster, groupId, {
        ...body(),
        dry_run: false,
        confirm_group_id: groupId,
      }),
    onSuccess: () => {
      setConfirming(false)
      setPreview(null)
      onApplied()
      onClose()
    },
    onError: (caught) => {
      setConfirming(false)
      setError(caught instanceof ApiError ? caught.message : String(caught))
    },
  })

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center p-4"
      style={{ background: 'var(--kp-overlay)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="reset-title"
    >
      <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-lg border border-subtle bg-surface shadow-lg">
        <div className="space-y-4 p-5">
          <div>
            <h2 id="reset-title" className="text-base font-semibold text-body">
              {t('reset.title')}
            </h2>
            <p className="mt-0.5 font-mono text-xs text-muted">{groupId}</p>
          </div>

          {error && <Banner tone="critical" title={t('errors.genericTitle')}>{error}</Banner>}

          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="reset-to" className="block text-xs font-medium text-muted">
                {t('reset.resetTo')}
              </label>
              <select
                id="reset-to"
                value={resetTo}
                onChange={(event) => {
                  setResetTo(event.target.value as ResetTo)
                  setPreview(null)
                }}
                className="mt-1 rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
              >
                <option value="earliest">{t('reset.earliest')}</option>
                <option value="latest">{t('reset.latest')}</option>
                <option value="offset">{t('reset.offset')}</option>
                <option value="timestamp">{t('reset.timestamp')}</option>
                <option value="shift">{t('reset.shift')}</option>
              </select>
            </div>

            {resetTo === 'offset' && (
              <input
                aria-label={t('reset.offset')}
                type="number"
                min={0}
                value={targetOffset}
                onChange={(event) => setTargetOffset(event.target.value)}
                className="w-32 rounded border border-subtle bg-surface px-2 py-1.5 text-sm tabular"
              />
            )}
            {resetTo === 'timestamp' && (
              <input
                aria-label={t('reset.timestamp')}
                type="datetime-local"
                value={timestamp}
                onChange={(event) => setTimestamp(event.target.value)}
                className="rounded border border-subtle bg-surface px-2 py-1.5 text-sm"
              />
            )}
            {resetTo === 'shift' && (
              <input
                aria-label={t('reset.shiftBy')}
                type="number"
                value={shiftBy}
                onChange={(event) => setShiftBy(event.target.value)}
                placeholder="-100"
                className="w-32 rounded border border-subtle bg-surface px-2 py-1.5 text-sm tabular"
              />
            )}

            <button
              type="button"
              onClick={() => dryRun.mutate()}
              disabled={dryRun.isPending}
              className="rounded border border-brand px-3 py-1.5 text-sm font-medium text-brand hover:bg-brand-tint disabled:opacity-50"
            >
              {dryRun.isPending ? t('reset.previewing') : t('reset.preview')}
            </button>
          </div>

          {preview && (
            <div className="space-y-3">
              {!preview.is_safe && (
                <Banner tone="critical" title={t('reset.blockedTitle')}>
                  {preview.blocked_reason}
                </Banner>
              )}

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded border border-subtle bg-surface-sunken px-3 py-2">
                  <div className="text-[11px] text-muted">{t('reset.partitions')}</div>
                  <div className="tabular text-lg font-semibold">{preview.changes.length}</div>
                </div>
                <div className="rounded border border-warn bg-warn-tint px-3 py-2">
                  <div className="text-[11px] text-muted">{t('reset.skipped')}</div>
                  <div className="tabular text-lg font-semibold text-warn">
                    {formatNumber(preview.total_skipped)}
                  </div>
                </div>
                <div className="rounded border border-info bg-info-tint px-3 py-2">
                  <div className="text-[11px] text-muted">{t('reset.replayed')}</div>
                  <div className="tabular text-lg font-semibold text-info">
                    {formatNumber(preview.total_replayed)}
                  </div>
                </div>
              </div>

              <p className="text-xs text-muted">{t('reset.explainer')}</p>

              <div className="max-h-56 overflow-auto rounded border border-subtle">
                <table className="w-full text-xs">
                  <thead className="bg-surface-sunken">
                    <tr>
                      <th className="px-2 py-1 text-left font-medium text-muted">
                        {t('groups.topic')}
                      </th>
                      <th className="px-2 py-1 text-right font-medium text-muted">
                        {t('topicDetail.partition')}
                      </th>
                      <th className="px-2 py-1 text-right font-medium text-muted">
                        {t('reset.current')}
                      </th>
                      <th className="px-2 py-1 text-right font-medium text-muted">
                        {t('reset.target')}
                      </th>
                      <th className="px-2 py-1 text-right font-medium text-muted">
                        {t('reset.change')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.changes.map((change) => (
                      <tr
                        key={`${change.topic}-${change.partition}`}
                        className="border-t border-subtle"
                      >
                        <td className="px-2 py-1 font-mono">{change.topic}</td>
                        <td className="px-2 py-1 text-right tabular">{change.partition}</td>
                        <td className="px-2 py-1 text-right tabular text-muted">
                          {change.current_offset ?? '—'}
                        </td>
                        <td className="px-2 py-1 text-right tabular font-medium">
                          {change.target_offset}
                        </td>
                        <td className="px-2 py-1 text-right tabular">
                          {change.messages_skipped > 0 && (
                            <span className="text-warn">
                              +{formatNumber(change.messages_skipped)} {t('reset.skip')}
                            </span>
                          )}
                          {change.messages_replayed > 0 && (
                            <span className="text-info">
                              −{formatNumber(change.messages_replayed)} {t('reset.replay')}
                            </span>
                          )}
                          {change.messages_skipped === 0 &&
                            change.messages_replayed === 0 && (
                              <span className="text-faint">{t('reset.noChange')}</span>
                            )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-subtle px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-subtle px-3 py-1.5 text-sm text-muted hover:bg-surface-sunken hover:text-body"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={!preview || !preview.is_safe || preview.changes.length === 0}
            className="rounded bg-critical px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {t('reset.apply')}
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={confirming}
        title={t('reset.confirmTitle')}
        body={t('reset.confirmBody', {
          skipped: formatNumber(preview?.total_skipped ?? 0),
          replayed: formatNumber(preview?.total_replayed ?? 0),
        })}
        confirmPhrase={groupId}
        confirmLabel={t('reset.apply')}
        busy={apply.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={() => apply.mutate()}
      />
    </div>
  )
}
