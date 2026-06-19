import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { Card, CodeBlock, EmptyState, Skeleton } from '@proofagent/ui'
import { fetchConfigAgents, fetchConfigDraftContract } from '../api/client'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'

interface ToolEntry {
  readonly agentId: string
  readonly agentName: string
  readonly draftId: string
  readonly toolsYaml: string
}

function parseToolNames(yaml: string): readonly string[] {
  return yaml
    .split('\n')
    .filter((l) => l.trim().startsWith('- name:'))
    .map((l) => l.replace(/.*- name:\s*['"]?/, '').replace(/['"]\s*$/, ''))
}

export function ToolsPage() {
  const [entries, setEntries] = useState<readonly ToolEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<readonly string[]>([])
  const { t, formatNumber } = useLocale()

  useEffect(() => {
    async function load() {
      try {
        const { data: agents } = await fetchConfigAgents()
        const withDrafts = agents.filter((a) => a.latest_draft_id)
        const contracts = await Promise.allSettled(
          withDrafts.map((a) => fetchConfigDraftContract(a.agent_id, a.latest_draft_id!)),
        )
        const results: readonly ToolEntry[] = withDrafts
          .map((agent, i) => {
            const res = contracts[i]
            if (res.status !== 'fulfilled' || !res.value.tools_yaml.trim()) return null
            return {
              agentId: agent.agent_id,
              agentName: agent.display_name,
              draftId: agent.latest_draft_id!,
              toolsYaml: res.value.tools_yaml,
            }
          })
          .filter((e): e is ToolEntry => e !== null)
        setEntries(results)
        setError(null)
      } catch {
        setError(t('tools.loadError'))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  function toggle(id: string) {
    setExpanded((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  if (loading) {
    return (
      <div className="max-w-7xl space-y-5">
        <PageHeader title={t('tools.title')} description={t('tools.description')} />
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="w-full max-w-7xl space-y-5 overflow-hidden max-md:max-w-[calc(100vw-2rem)]">
      <PageHeader title={t('tools.title')} description={t('tools.description')} />

      {error ? (
        <div className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-fg)]">
          {error}
        </div>
      ) : entries.length === 0 ? (
        <Card>
          <EmptyState message={t('tools.empty')} />
        </Card>
      ) : (
        <div className="min-w-0 space-y-3">
          {entries.map((entry) => {
            const toolNames = parseToolNames(entry.toolsYaml)
            const isOpen = expanded.includes(entry.agentId)
            const preview = toolNames.slice(0, 2).join(', ')
            return (
              <Card key={entry.agentId} className="min-w-0 overflow-hidden p-0">
                <button
                  onClick={() => toggle(entry.agentId)}
                  className="flex w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-5 py-4 text-left transition-colors hover:bg-[var(--bg-hover)]"
                >
                  <ChevronRight
                    size={16}
                    className={`shrink-0 text-[var(--text-muted)] transition-transform ${
                      isOpen ? 'rotate-90' : ''
                    }`}
                  />
                  <span className="min-w-0 flex-1 basis-40 truncate font-medium text-[var(--text-primary)]">
                    {entry.agentName}
                  </span>
                  <span className="shrink-0 text-sm text-[var(--text-secondary)]">
                    {formatNumber(toolNames.length)} {t('tools.count')}
                  </span>
                  {preview && (
                    <span className="min-w-0 basis-full truncate pl-6 text-xs text-[var(--text-muted)] md:basis-auto md:pl-0">
                      &mdash; {preview}
                    </span>
                  )}
                </button>
                {isOpen && (
                  <div className="space-y-3 px-5 pb-4">
                    <CodeBlock>{entry.toolsYaml}</CodeBlock>
                    <Link
                      to={`/agents/${entry.agentId}/drafts/${entry.draftId}`}
                      className="text-sm text-[var(--accent)] hover:underline"
                    >
                      {t('tools.editInAgent')}
                    </Link>
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
