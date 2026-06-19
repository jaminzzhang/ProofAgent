import { Link } from 'react-router-dom'
import {
  Activity,
  Boxes,
  Brain,
  ClipboardList,
  Cpu,
  Eye,
  FileText,
  GitBranch,
  LayoutDashboard,
  type LucideIcon,
  ScrollText,
  Settings2,
  ShieldCheck,
  Workflow,
  Wrench,
} from 'lucide-react'
import { cn } from '@proofagent/ui'
import { useLocale } from '../../i18n/locale'
import { TopNav } from '../TopNav'

interface Tab {
  id: string
  label: string
}

interface WorkspaceGroup {
  title: string
  items: Tab[]
}

interface AgentDetailShellProps {
  agentName: string
  modules: Tab[]
  lifecycle: Tab[]
  activeModule: string
  onModuleChange: (moduleId: string) => void
  children: React.ReactNode
}

/** Icon per module/lifecycle id — gives the secondary nav visual parity with the main Sidebar. */
const TAB_ICON: Record<string, LucideIcon> = {
  general: LayoutDashboard,
  workflow: Workflow,
  skills: Boxes,
  knowledge: FileText,
  tools: Wrench,
  policy: ShieldCheck,
  model: Cpu,
  memory: Brain,
  response: ScrollText,
  validate: ClipboardList,
  versions: GitBranch,
  contract: Settings2,
  monitor: Eye,
}

function tabIcon(id: string): LucideIcon {
  return TAB_ICON[id] ?? Activity
}

export function AgentDetailShell({
  agentName,
  modules,
  lifecycle,
  activeModule,
  onModuleChange,
  children,
}: AgentDetailShellProps) {
  const { t } = useLocale()
  const moduleById = new Map(modules.map((module) => [module.id, module]))
  const lifecycleById = new Map(lifecycle.map((tab) => [tab.id, tab]))
  const groups: WorkspaceGroup[] = [
    {
      title: t('agentDetail.groupOverview'),
      items: ['general']
        .map((id) => moduleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
    {
      title: t('agentDetail.groupDesign'),
      items: ['workflow', 'skills', 'knowledge', 'tools', 'policy', 'model', 'memory', 'response']
        .map((id) => moduleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
    {
      title: t('agentDetail.groupVerify'),
      items: ['validate', 'contract']
        .map((id) => lifecycleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
    {
      title: t('agentDetail.groupRelease'),
      items: ['versions']
        .map((id) => lifecycleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
    {
      title: t('agentDetail.groupObserve'),
      items: ['monitor']
        .map((id) => lifecycleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
  ].filter((group) => group.items.length > 0)

  return (
    <div
      data-testid="agent-detail-layout"
      className="flex h-screen w-screen min-w-0 flex-col overflow-hidden bg-[var(--bg-base)]"
    >
      {/* Unified TopNav: theme toggle stays on (consistent with the rest of the app). */}
      <TopNav
        title={
          <nav aria-label={t('agentDetail.breadcrumb')}>
            <ol className="flex min-w-0 items-center gap-2">
              <li className="shrink-0">
                <Link
                  to="/agents"
                  className="rounded-md text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                >
                  {t('agents.title')}
                </Link>
              </li>
              <li aria-hidden="true" className="shrink-0 text-[var(--text-muted)]">
                /
              </li>
              <li aria-current="page" className="min-w-0 truncate text-[var(--text-primary)]">
                {agentName}
              </li>
            </ol>
          </nav>
        }
      />

      {/* Workspace: secondary sidebar + content. Width/padding aligned with the main Sidebar. */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col lg:flex-row">
        <aside className="min-w-0 shrink-0 overflow-y-auto border-b border-[var(--border)] bg-[var(--bg-surface)] pb-4 pt-5 lg:w-56 lg:border-b-0 lg:border-r max-md:w-full">
          <nav aria-label={t('agentDetail.navigation')} className="px-3">
            <div className="space-y-5 max-md:flex max-md:flex-wrap max-md:gap-x-6 max-md:space-y-0">
              {groups.map((group) => (
                <section key={group.title}>
                  <h3 className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    {group.title}
                  </h3>
                  <div className="space-y-0.5">
                    {group.items.map((item) => {
                      const isActive = activeModule === item.id
                      const Icon = tabIcon(item.id)
                      return (
                        <button
                          key={item.id}
                          onClick={() => onModuleChange(item.id)}
                          className={cn(
                            'group relative flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]',
                            isActive
                              ? 'bg-[var(--accent-subtle)] text-[var(--text-primary)]'
                              : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
                          )}
                          aria-current={isActive ? 'page' : undefined}
                        >
                          {isActive && (
                            <span
                              aria-hidden="true"
                              className="absolute left-0 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-full bg-[var(--accent)]"
                            />
                          )}
                          <Icon
                            size={16}
                            strokeWidth={2}
                            className={cn(
                              'shrink-0 transition-colors',
                              isActive
                                ? 'text-[var(--text-primary)]'
                                : 'text-[var(--text-muted)] group-hover:text-current',
                            )}
                          />
                          <span className="truncate">{item.label}</span>
                        </button>
                      )
                    })}
                  </div>
                </section>
              ))}
            </div>
          </nav>
        </aside>

        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto px-8 py-8 max-md:px-4 max-md:py-5">
          <div className="mx-auto min-w-0 max-w-7xl pb-12">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
