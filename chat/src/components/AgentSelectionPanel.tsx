import type { PublishedAgentDirectoryEntry } from '../api/types'
import { useLocale } from '../i18n/locale'

interface AgentSelectionPanelProps {
  title: string
  description: string
  agents: PublishedAgentDirectoryEntry[]
  emptyTitle: string
  emptyDescription: string
  unavailableAgentId?: string
  onSelect: (agentId: string) => void
}

export function AgentSelectionPanel({
  title,
  description,
  agents,
  emptyTitle,
  emptyDescription,
  unavailableAgentId,
  onSelect,
}: AgentSelectionPanelProps) {
  const { t } = useLocale()

  if (unavailableAgentId) {
    return (
      <CenteredPanel
        title={t('agentSelection.unavailable', `${unavailableAgentId} is unavailable`).replace('{agentId}', unavailableAgentId)}
        description={emptyDescription}
      />
    )
  }

  if (agents.length === 0) {
    return <CenteredPanel title={emptyTitle} description={emptyDescription} />
  }

  return (
    <section className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center px-4">
      <div className="space-y-2">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">{title}</h1>
        <p className="text-sm leading-6 text-[var(--text-secondary)]">{description}</p>
      </div>
      <div className="mt-6 grid gap-3">
        {agents.map((agent) => (
          <button
            key={agent.agent_id}
            type="button"
            onClick={() => onSelect(agent.agent_id)}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4 text-left transition hover:border-[var(--accent)] hover:bg-[var(--bg-hover)]"
          >
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              {agent.display_name}
            </span>
            <span className="mt-1 block text-xs font-mono text-[var(--text-muted)]">
              {agent.agent_id}
            </span>
            <span className="mt-2 block text-sm leading-6 text-[var(--text-secondary)]">
              {agent.purpose}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

function CenteredPanel({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <section className="flex h-full flex-col items-center justify-center px-4 text-center">
      <h1 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h1>
      <p className="mt-2 max-w-[360px] text-sm leading-6 text-[var(--text-secondary)]">
        {description}
      </p>
    </section>
  )
}
