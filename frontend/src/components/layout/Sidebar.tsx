import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

interface NavItem {
  to: string
  labelKey: string
  icon: string
}

// Order matches the brief's sidebar spec. Pages that arrive in later
// milestones render an explicit "not built yet" state rather than 404.
const ITEMS: NavItem[] = [
  { to: '/', labelKey: 'nav.overview', icon: '▣' },
  { to: '/topics', labelKey: 'nav.topics', icon: '≡' },
  { to: '/consumer-groups', labelKey: 'nav.consumerGroups', icon: '⇄' },
  { to: '/messages', labelKey: 'nav.messages', icon: '✉' },
  { to: '/replication', labelKey: 'nav.replication', icon: '⧉' },
  { to: '/metrics', labelKey: 'nav.metrics', icon: '◴' },
  { to: '/dashboards', labelKey: 'nav.dashboards', icon: '◫' },
  { to: '/flow-map', labelKey: 'nav.flowMap', icon: '⤳' },
  { to: '/schemas', labelKey: 'nav.schemas', icon: '{}' },
  { to: '/acls', labelKey: 'nav.acls', icon: '⚿' },
  { to: '/alerts', labelKey: 'nav.alerts', icon: '◉' },
  { to: '/audit', labelKey: 'nav.audit', icon: '❐' },
  { to: '/settings', labelKey: 'nav.settings', icon: '⚙' },
]

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const { t } = useTranslation()

  return (
    <nav
      aria-label={t('nav.mainNavigation')}
      className={`flex shrink-0 flex-col border-r border-subtle bg-surface transition-[width] duration-150 ${
        collapsed ? 'w-14' : 'w-56'
      }`}
    >
      <ul className="flex-1 space-y-0.5 p-2">
        {ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === '/'}
              title={collapsed ? t(item.labelKey) : undefined}
              className={({ isActive }) =>
                [
                  'flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-brand-tint font-medium text-brand'
                    : 'text-muted hover:bg-surface-sunken hover:text-body',
                ].join(' ')
              }
            >
              <span aria-hidden="true" className="w-4 shrink-0 text-center">
                {item.icon}
              </span>
              {collapsed ? (
                <span className="sr-only">{t(item.labelKey)}</span>
              ) : (
                <span className="truncate">{t(item.labelKey)}</span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="m-2 rounded-md px-2.5 py-2 text-left text-sm text-muted hover:bg-surface-sunken hover:text-body"
      >
        <span aria-hidden="true">{collapsed ? '»' : '«'}</span>
        {!collapsed && <span className="ml-3">{t('nav.collapseSidebar')}</span>}
        {collapsed && <span className="sr-only">{t('nav.expandSidebar')}</span>}
      </button>
    </nav>
  )
}
