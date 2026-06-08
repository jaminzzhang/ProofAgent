import { Link } from 'react-router-dom'
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

export function AgentDetailShell({
  agentName,
  modules,
  lifecycle,
  activeModule,
  onModuleChange,
  children,
}: AgentDetailShellProps) {
  const moduleById = new Map(modules.map((module) => [module.id, module]))
  const lifecycleById = new Map(lifecycle.map((tab) => [tab.id, tab]))
  const groups: WorkspaceGroup[] = [
    {
      title: 'Overview',
      items: ['general']
        .map((id) => moduleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
    {
      title: 'Configure',
      items: ['workflow', 'knowledge', 'tools', 'policy', 'model', 'memory', 'response']
        .map((id) => moduleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
    {
      title: 'Lifecycle',
      items: ['validate', 'versions', 'contract']
        .map((id) => lifecycleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
    {
      title: 'Observe',
      items: ['monitor']
        .map((id) => lifecycleById.get(id))
        .filter((item): item is Tab => Boolean(item)),
    },
  ].filter((group) => group.items.length > 0)

  return (
    <div
      data-testid="agent-detail-layout"
      className="grid h-screen w-screen min-w-0 grid-rows-[4rem_minmax(0,1fr)] overflow-hidden bg-[var(--bg-base)]"
    >
      <TopNav
        title={
          <nav aria-label="Agent breadcrumb">
            <ol className="flex min-w-0 items-center gap-2">
              <li className="shrink-0">
                <Link
                  to="/agents"
                  className="rounded-md text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                >
                  Agents
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
        status={null}
        showThemeToggle={false}
      />

      <div className="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] lg:grid-cols-[260px_minmax(0,1fr)] lg:grid-rows-1">
        <aside className="min-w-0 overflow-y-auto border-b border-[var(--border)] bg-[var(--bg-surface)] lg:border-b-0 lg:border-r">
          <nav
            aria-label="Agent navigation"
            className="p-3"
          >
            <div className="grid gap-3 sm:grid-cols-4 lg:block lg:space-y-5">
              {groups.map((group) => (
                <section key={group.title}>
                  <h3 className="mb-2 px-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    {group.title}
                  </h3>
                  <div className="space-y-1">
                    {group.items.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => onModuleChange(item.id)}
                        className={`w-full cursor-pointer rounded-md px-3 py-2 text-left text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] ${
                          activeModule === item.id
                            ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                            : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]'
                        }`}
                        aria-current={activeModule === item.id ? 'page' : undefined}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </nav>
        </aside>

        <main className="min-w-0 overflow-y-auto px-5 py-5 lg:px-8 lg:py-6">
          <div className="min-w-0 pb-12">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
