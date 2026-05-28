import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchConfigAgents, fetchConfigDraftContract } from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { CodeBlock } from '../components/CodeBlock'

interface KnowledgeEntry {
  readonly agentId: string
  readonly agentName: string
  readonly draftId: string
  readonly knowledgeSection: string
}

function extractSection(yaml: string, sectionName: string): string {
  const lines = yaml.split('\n')
  const start = lines.findIndex(l => l.match(new RegExp(`^${sectionName}:`)))
  if (start === -1) return ''
  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].trim() && !lines[i].startsWith(' ')) { end = i; break }
  }
  return lines.slice(start, end).join('\n')
}

export function KnowledgePage() {
  const [entries, setEntries] = useState<readonly KnowledgeEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const { data: agents } = await fetchConfigAgents()
        const drafts = agents.filter(a => a.latest_draft_id)
        const contracts = await Promise.allSettled(
          drafts.map(a => fetchConfigDraftContract(a.agent_id, a.latest_draft_id!))
        )
        const results: KnowledgeEntry[] = []
        for (let i = 0; i < drafts.length; i++) {
          const res = contracts[i]
          if (res.status !== 'fulfilled') continue
          const section = extractSection(res.value.agent_yaml, 'knowledge')
          if (!section) continue
          results.push({ agentId: drafts[i].agent_id, agentName: drafts[i].display_name, draftId: drafts[i].latest_draft_id!, knowledgeSection: section })
        }
        if (!controller.signal.aborted) { setEntries(results); setError(null) }
      } catch { if (!controller.signal.aborted) setError('Unable to load knowledge sources.') }
      finally { if (!controller.signal.aborted) setLoading(false) }
    }
    load()
    return () => controller.abort()
  }, [])

  const toggle = (id: string) =>
    setExpanded(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next })

  if (loading) return <div className="flex justify-center py-12"><LoadingSpinner /></div>

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="mb-8">
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Knowledge Sources</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">Browse knowledge configurations across all agents. Edit within agent configuration.</p>
      </div>
      {error || entries.length === 0 ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-6">
          <EmptyState message={error ?? 'No knowledge sources configured.'} />
        </div>
      ) : (
        <div className="space-y-3">
          {entries.map(entry => {
            const isOpen = expanded.has(entry.agentId)
            const provider = entry.knowledgeSection.split('\n').find(l => /^\s+provider:/.test(l))
            const path = entry.knowledgeSection.split('\n').find(l => /^\s+path:/.test(l))
            return (
              <div key={entry.agentId} className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)]">
                <button onClick={() => toggle(entry.agentId)} className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-[var(--bg-hover)] transition-colors">
                  <span className={`text-[var(--text-muted)] transition-transform ${isOpen ? 'rotate-90' : ''}`}>&#9654;</span>
                  <span className="font-medium text-[var(--text-primary)]">{entry.agentName}</span>
                  {provider && <span className="text-xs text-[var(--text-muted)]">{provider.trim()}</span>}
                  {path && <span className="text-xs text-[var(--text-secondary)] font-mono">{path.trim()}</span>}
                  <Link to={`/agents/${entry.agentId}/drafts/${entry.draftId}`} onClick={e => e.stopPropagation()} className="ml-auto text-xs text-[var(--accent)] hover:underline">Edit in Agent</Link>
                </button>
                {isOpen && (
                  <div className="border-t border-[var(--border)] px-5 py-4"><CodeBlock>{entry.knowledgeSection}</CodeBlock></div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
