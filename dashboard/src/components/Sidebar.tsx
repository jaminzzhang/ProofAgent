import {
  Activity,
  Bot,
  BookOpen,
  Boxes,
  Cpu,
  LayoutDashboard,
  Settings,
  ShieldCheck,
  Wrench,
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
  { to: '/handoffs', labelKey: 'nav.handoffs', icon: Boxes },
  { to: '/approvals', labelKey: 'nav.approvals', icon: ShieldCheck },
]

const CONFIGURATION_ITEMS: NavEntry[] = [
  { to: '/agents', labelKey: 'nav.agents', icon: Bot },
  { to: '/policies', labelKey: 'nav.policies', icon: ShieldCheck },
  { to: '/knowledge', labelKey: 'nav.knowledge', icon: BookOpen },
  { to: '/models', labelKey: 'nav.models', icon: Cpu },
  { to: '/tools', labelKey: 'nav.tools', icon: Wrench },
]

export function Sidebar() {
  const { t } = useLocale()

  return (
    <aside className="flex w-56 shrink-0 flex-col overflow-y-auto border-r border-[var(--border)] bg-[var(--bg-surface)] pb-4 pt-5 max-md:w-full max-md:border-b max-md:border-r-0 max-md:pt-2 max-md:pb-2">
      <nav
        className="flex-1 px-3 max-md:flex max-md:gap-1 max-md:space-y-0 max-md:overflow-x-auto"
        aria-label={t('nav.main')}
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

      {/* Settings: marked as a future surface rather than a dead hash link */}
      <div className="mt-auto px-3 max-md:hidden">
        <div
          className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-[var(--text-muted)]"
          title="Settings — coming soon"
        >
          <Settings size={16} strokeWidth={2} className="shrink-0" />
          <span>{t('nav.settings')}</span>
        </div>
      </div>
    </aside>
  )
}
