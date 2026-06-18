import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchConfigAgents, fetchConfigDraftContract } from '../api/client'
import type { ConfigAgentSummary } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { CodeBlock } from '../components/CodeBlock'
import { useLocale } from '../i18n/locale'

interface PolicyEntry {
  readonly agentId: string
  readonly agentName: string
  readonly draftId: string
  readonly policyYaml: string
}

function countRules(yaml: string): number {
  return yaml.split('\n').filter((line) => line.match(/^[\s]*- rule_id:/)).length
}

export function PoliciesPage() {
  const [entries, setEntries] = useState<readonly PolicyEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<readonly string[]>([])
  const { t, formatNumber } = useLocale()

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const agentsRes = await fetchConfigAgents()
        const agents: readonly ConfigAgentSummary[] = agentsRes.data
        const results: PolicyEntry[] = []

        const fetches = agents
          .filter((agent) => agent.latest_draft_id)
          .map(async (agent) => {
            try {
              const contract = await fetchConfigDraftContract(agent.agent_id, agent.latest_draft_id!)
              if (contract.policy_yaml?.trim()) {
                results.push({
                  agentId: agent.agent_id,
                  agentName: agent.display_name,
                  draftId: agent.latest_draft_id!,
                  policyYaml: contract.policy_yaml,
                })
              }
            } catch { /* skip agents with missing contracts */ }
          })

        await Promise.all(fetches)
        if (!cancelled) {
          setEntries(results)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('policies.loadError'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  function toggle(agentId: string) {
    setExpanded((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId],
    )
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">{t('policies.title')}</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">{t('policies.description')}</p>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><LoadingSpinner /></div>
      ) : error ? (
        <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      ) : entries.length === 0 ? (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
          <EmptyState message={t('policies.empty')} />
        </div>
      ) : (
        <div className="space-y-3">
          {entries.map((entry) => {
            const isOpen = expanded.includes(entry.agentId)
            const rules = countRules(entry.policyYaml)
            return (
              <div key={entry.agentId} className="border border-[var(--border)] rounded-lg bg-[var(--bg-surface)] overflow-hidden">
                <button
                  onClick={() => toggle(entry.agentId)}
                  className="flex w-full items-center justify-between gap-4 px-5 py-3 text-left hover:bg-[var(--bg-hover)] transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`text-[var(--text-muted)] transition-transform ${isOpen ? 'rotate-90' : ''}`}>&#9654;</span>
                    <span className="font-medium text-[var(--text-primary)] truncate">{entry.agentName}</span>
                    <span className="shrink-0 rounded-md bg-[var(--bg-base)] px-2 py-0.5 text-xs font-mono text-[var(--text-secondary)]">
                      {formatNumber(rules)} {rules === 1 ? t('policies.rule') : t('policies.rules')}
                    </span>
                  </div>
                  <Link
                    to={`/agents/${entry.agentId}/drafts/${entry.draftId}`}
                    onClick={(e) => e.stopPropagation()}
                    className="shrink-0 text-xs text-[var(--accent)] hover:underline"
                  >
                    {t('policies.editInAgent')}
                  </Link>
                </button>
                {isOpen && (
                  <div className="border-t border-[var(--border)] px-5 py-4">
                    <CodeBlock>{entry.policyYaml}</CodeBlock>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
