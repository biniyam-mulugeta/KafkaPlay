/**
 * Dense, sortable, filterable table.
 *
 * Rows are windowed manually rather than through a virtualiser dependency:
 * the console must stay responsive on clusters with thousands of topics, but
 * a plain slice with a "show more" control is simpler than a virtual list and
 * behaves better with keyboard navigation and find-in-page.
 */

import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

export interface Column<T> {
  key: string
  header: string
  /** Cell contents. */
  render: (row: T) => ReactNode
  /** Value used for sorting; omit to make the column unsortable. */
  sortValue?: (row: T) => string | number | null
  align?: 'left' | 'right'
  width?: string
}

const PAGE_SIZE = 100

export function DataTable<T>({
  rows,
  columns,
  getRowKey,
  searchPlaceholder,
  searchValue,
  onSearchChange,
  emptyState,
  initialSortKey,
}: {
  rows: T[]
  columns: Column<T>[]
  getRowKey: (row: T) => string
  searchPlaceholder?: string
  searchValue?: string
  onSearchChange?: (value: string) => void
  emptyState?: ReactNode
  initialSortKey?: string
}) {
  const { t } = useTranslation()
  const [sortKey, setSortKey] = useState<string | null>(initialSortKey ?? null)
  const [descending, setDescending] = useState(false)
  const [visible, setVisible] = useState(PAGE_SIZE)

  const sorted = useMemo(() => {
    const column = columns.find((c) => c.key === sortKey)
    if (!column?.sortValue) return rows
    const sortValue = column.sortValue
    return [...rows].sort((a, b) => {
      const left = sortValue(a)
      const right = sortValue(b)
      // Nulls sort last regardless of direction: "unknown" is not "zero".
      if (left === null && right === null) return 0
      if (left === null) return 1
      if (right === null) return -1
      const result =
        typeof left === 'number' && typeof right === 'number'
          ? left - right
          : String(left).localeCompare(String(right))
      return descending ? -result : result
    })
  }, [rows, columns, sortKey, descending])

  const shown = sorted.slice(0, visible)

  function toggleSort(key: string) {
    if (sortKey === key) {
      setDescending((value) => !value)
    } else {
      setSortKey(key)
      setDescending(false)
    }
  }

  return (
    <div className="space-y-3">
      {onSearchChange && (
        <input
          type="search"
          value={searchValue ?? ''}
          onChange={(event) => {
            onSearchChange(event.target.value)
            setVisible(PAGE_SIZE)
          }}
          placeholder={searchPlaceholder ?? t('common.search')}
          aria-label={searchPlaceholder ?? t('common.search')}
          className="w-full max-w-sm rounded border border-subtle bg-surface px-3 py-1.5 text-sm text-body"
        />
      )}

      {rows.length === 0 ? (
        emptyState
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-subtle bg-surface">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-subtle bg-surface-sunken">
                  {columns.map((column) => (
                    <th
                      key={column.key}
                      scope="col"
                      style={column.width ? { width: column.width } : undefined}
                      className={`px-3 py-2 text-xs font-medium text-muted ${
                        column.align === 'right' ? 'text-right' : 'text-left'
                      }`}
                      aria-sort={
                        sortKey === column.key
                          ? descending
                            ? 'descending'
                            : 'ascending'
                          : undefined
                      }
                    >
                      {column.sortValue ? (
                        <button
                          type="button"
                          onClick={() => toggleSort(column.key)}
                          className="inline-flex items-center gap-1 hover:text-body"
                        >
                          {column.header}
                          <span aria-hidden="true" className="text-faint">
                            {sortKey === column.key ? (descending ? '▾' : '▴') : '⇅'}
                          </span>
                        </button>
                      ) : (
                        column.header
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr
                    key={getRowKey(row)}
                    className="border-b border-subtle last:border-0 hover:bg-surface-sunken"
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={`px-3 py-1.5 ${
                          column.align === 'right' ? 'text-right' : 'text-left'
                        }`}
                      >
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {sorted.length > visible && (
            <div className="flex items-center gap-3 text-xs text-muted">
              <span>
                {shown.length} / {sorted.length}
              </span>
              <button
                type="button"
                onClick={() => setVisible((value) => value + PAGE_SIZE)}
                className="rounded border border-subtle px-2 py-1 hover:bg-surface-sunken hover:text-body"
              >
                {t('table.showMore')}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
