import { Link } from 'react-router-dom'

interface Tab {
  id: string
  label: string
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
  return (
    <div className="w-full min-w-0 max-w-6xl space-y-6 overflow-hidden">
      {/* Header */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <Link to="/agents" className="text-xs font-medium tracking-wide text-[var(--text-muted)] hover:text-[var(--text-primary)] uppercase">
          &larr; Back to Agents
        </Link>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)] mt-4">
          {agentName}
        </h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Draft configuration workspace
        </p>
      </div>

      {/* Vertical tabs + content */}
      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        {/* Tab navigation */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
          {/* CONFIGURE section */}
          <div className="p-4 border-b border-[var(--border)]">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
              CONFIGURE
            </h3>
            <div className="space-y-1">
              {modules.map((module) => (
                <button
                  key={module.id}
                  onClick={() => onModuleChange(module.id)}
                  className={`w-full text-left px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                    activeModule === module.id
                      ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                      : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                  }`}
                >
                  {module.label}
                </button>
              ))}
            </div>
          </div>

          {/* LIFECYCLE section */}
          <div className="p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
              LIFECYCLE
            </h3>
            <div className="space-y-1">
              {lifecycle.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => onModuleChange(tab.id)}
                  className={`w-full text-left px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                    activeModule === tab.id
                      ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                      : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Content area */}
        <div className="min-w-0">
          {children}
        </div>
      </div>
    </div>
  )
}
