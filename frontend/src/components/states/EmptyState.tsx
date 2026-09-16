import type { ReactNode } from 'react'

/** Empty and error states always say what to do next, never just "no data". */
export function EmptyState({
  title,
  body,
  action,
  icon = '◇',
}: {
  title: string
  body?: ReactNode
  action?: ReactNode
  icon?: string
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-strong bg-surface px-6 py-14 text-center">
      <span aria-hidden="true" className="text-3xl text-faint">
        {icon}
      </span>
      <h2 className="mt-3 text-base font-semibold text-body">{title}</h2>
      {body ? <p className="mt-1 max-w-md text-sm text-muted">{body}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

/** Skeletons rather than spinners: the layout should not jump when data lands. */
export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse rounded bg-surface-sunken ${className}`}
    />
  )
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-9 w-full" />
      ))}
    </div>
  )
}
