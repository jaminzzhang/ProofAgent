import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchConfigAgents, fetchConfigDraftContract } from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { CodeBlock } from '../components/CodeBlock'
import { useLocale } from '../i18n/locale'

interface ToolEntry {
  readonly agentId: string
  readonly agentName: string
  readonly draftId: string
  readonly toolsYaml: string
}

function parseToolNames(yaml: string): readonly string[] {
  return yaml.split('\n').filter(l => l.trim().startsWith('- name:'))
    .map(l => l.replace(/.*- name:\s*['"]?/, '').replace(/['"]\s*$/, ''))
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
        const withDrafts = agents.filter(a => a.latest_draft_id)
        const contracts = await Promise.allSettled(
          withDrafts.map(a => fetchConfigDraftContract(a.agent_id, a.latest_draft_id!))
        )
        const results: readonly ToolEntry[] = withDrafts
          .map((agent, i) => {
            const res = contracts[i]
            if (res.status !== 'fulfilled' || !res.value.tools_yaml.trim()) return null
            return { agentId: agent.agent_id, agentName: agent.display_name, draftId: agent.latest_draft_id!, toolsYaml: res.value.tools_yaml }
          }).filter((e): e is ToolEntry => e !== null)
        setEntries(results)
        setError(null)
      } catch {
        setError(t('tools.loadError'))
      } finally { setLoading(false) }
    }
    load()
  }, [])

  function toggle(id: string) {
    setExpanded(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  if (loading) {
    return <div className="space-y-6 max-w-6xl"><div className="py-12 flex justify-center"><LoadingSpinner /></div></div>
  }

  return (
    <div className="w-full max-w-6xl space-y-6 overflow-hidden max-md:max-w-[calc(100vw-2rem)]">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">{t('tools.title')}</h2>
        <p className="mt-1 max-w-full break-words text-sm text-[var(--text-muted)]">{t('tools.description')}</p>
      </div>

      {error ? (
        <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      ) : entries.length === 0 ? (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
          <EmptyState message={t('tools.empty')} />
        </div>
      ) : (
        <div className="space-y-3 min-w-0">
          {entries.map(entry => {
            const toolNames = parseToolNames(entry.toolsYaml)
            const isOpen = expanded.includes(entry.agentId)
            const preview = toolNames.slice(0, 2).join(', ')
            return (
              <div key={entry.agentId} className="min-w-0 bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
                <button onClick={() => toggle(entry.agentId)}
                  className="w-full min-w-0 flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-4 text-left hover:bg-[var(--bg-hover)] transition-colors">
                  <span className={`shrink-0 text-[var(--text-muted)] transition-transform ${isOpen ? 'rotate-90' : ''}`}>&#9654;</span>
                  <span className="min-w-0 flex-1 basis-40 truncate font-medium text-[var(--text-primary)]">{entry.agentName}</span>
                  <span className="shrink-0 text-sm text-[var(--text-secondary)]">{formatNumber(toolNames.length)} {t('tools.count')}</span>
                  {preview && <span className="min-w-0 basis-full truncate pl-6 text-xs text-[var(--text-muted)] md:basis-auto md:pl-0">&mdash; {preview}</span>}
                </button>
                {isOpen && (
                  <div className="px-5 pb-4 space-y-3">
                    <CodeBlock>{entry.toolsYaml}</CodeBlock>
                    <Link to={`/agents/${entry.agentId}/drafts/${entry.draftId}`} className="text-sm text-[var(--accent)] hover:underline">{t('tools.editInAgent')}</Link>
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
