import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { Badge, Card, CodeBlock, EmptyState, Skeleton } from '@proofagent/ui'
import { fetchConfigAgents, fetchConfigDraftContract } from '../api/client'
import type { ConfigAgentSummary } from '../api/types'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'

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
            } catch {
              /* skip agents with missing contracts */
            }
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
    return () => {
      cancelled = true
    }
  }, [])

  function toggle(agentId: string) {
    setExpanded((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId],
    )
  }

  return (
    <div className="max-w-6xl space-y-5">
      <PageHeader title={t('policies.title')} description={t('policies.description')} />

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-fg)]">
          {error}
        </div>
      ) : entries.length === 0 ? (
        <Card>
          <EmptyState message={t('policies.empty')} />
        </Card>
      ) : (
        <div className="space-y-3">
          {entries.map((entry) => {
            const isOpen = expanded.includes(entry.agentId)
            const rules = countRules(entry.policyYaml)
            return (
              <Card key={entry.agentId} className="overflow-hidden p-0">
                <button
                  onClick={() => toggle(entry.agentId)}
                  className="flex w-full items-center justify-between gap-4 px-5 py-3.5 text-left transition-colors hover:bg-[var(--bg-hover)]"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <ChevronRight
                      size={16}
                      className={`shrink-0 text-[var(--text-muted)] transition-transform ${
                        isOpen ? 'rotate-90' : ''
                      }`}
                    />
                    <span className="truncate font-medium text-[var(--text-primary)]">
                      {entry.agentName}
                    </span>
                    <Badge variant="subtle" className="font-mono">
                      {formatNumber(rules)} {rules === 1 ? t('policies.rule') : t('policies.rules')}
                    </Badge>
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
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
