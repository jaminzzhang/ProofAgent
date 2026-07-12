import {
  Activity,
  Bot,
  BookOpen,
  Cpu,
  LayoutDashboard,
  Settings,
  ShieldCheck,
  Wrench,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { NavigationSection } from './navigation/NavigationSection'
import { NavigationItem } from './navigation/NavigationItem'
import { useLocale } from '../i18n/locale'

interface NavEntry {
  to: string
  labelKey: string
  icon: LucideIcon
}

const MONITORING_ITEMS: NavEntry[] = [
  { to: '/', labelKey: 'nav.overview', icon: LayoutDashboard },
  { to: '/runs', labelKey: 'nav.runs', icon: Activity },
]

const CONFIGURATION_ITEMS: NavEntry[] = [
  { to: '/agents', labelKey: 'nav.agents', icon: Bot },
  { to: '/policies', labelKey: 'nav.policies', icon: ShieldCheck },
  { to: '/knowledge', labelKey: 'nav.knowledge', icon: BookOpen },
  { to: '/models', labelKey: 'nav.models', icon: Cpu },
  { to: '/tools', labelKey: 'nav.tools', icon: Wrench },
]

interface SidebarProps {
  /** Mobile drawer open state. Desktop is always shown, regardless. */
  open?: boolean
  /** Called to close the mobile drawer (scrim click, nav, close button). */
  onClose?: () => void
}

export function Sidebar({ open = false, onClose }: SidebarProps) {
  const { t } = useLocale()

  const nav = (
    <nav
      className="flex-1 space-y-5 px-3 max-md:flex max-md:gap-1 max-md:space-y-0 max-md:overflow-x-auto"
      aria-label={t('nav.main')}
      onClick={() => onClose?.()}
    >
      <NavigationSection title={t('nav.monitoring')}>
        {MONITORING_ITEMS.map((item) => (
          <NavigationItem
            key={item.labelKey}
            to={item.to}
            label={t(item.labelKey)}
            icon={item.icon}
          />
        ))}
      </NavigationSection>

      <NavigationSection title={t('nav.configuration')}>
        {CONFIGURATION_ITEMS.map((item) => (
          <NavigationItem
            key={item.labelKey}
            to={item.to}
            label={t(item.labelKey)}
            icon={item.icon}
          />
        ))}
      </NavigationSection>
    </nav>
  )

  return (
    <>
      {/* Desktop: fixed aside, always visible. Hidden on mobile. */}
      <aside className="hidden w-56 shrink-0 flex-col overflow-y-auto border-r border-[var(--border)] bg-[var(--bg-surface)] pb-4 pt-5 md:flex">
        {nav}
        {/* Settings: marked as a future surface rather than a dead hash link */}
        <div className="mt-auto px-3">
          <div
            className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-[var(--text-muted)]"
            title="Settings — coming soon"
          >
            <Settings size={16} strokeWidth={2} className="shrink-0" />
            <span>{t('nav.settings')}</span>
          </div>
        </div>
      </aside>

      {/* Mobile: slide-over drawer + scrim, only when open. */}
      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            data-testid="sidebar-scrim"
            className="absolute inset-0 bg-black/40"
            onClick={() => onClose?.()}
            aria-hidden
          />
          <aside className="absolute left-0 top-0 flex h-full w-72 max-w-[85%] flex-col overflow-y-auto border-r border-[var(--border)] bg-[var(--bg-surface)] pb-4 pt-5 shadow-xl">
            <div className="flex justify-end px-3">
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => onClose?.()}
                className="rounded-md p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
              >
                <X size={18} />
              </button>
            </div>
            {nav}
          </aside>
        </div>
      )}
    </>
  )
}
