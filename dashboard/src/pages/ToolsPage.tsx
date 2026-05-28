import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchConfigAgents, fetchConfigDraftContract } from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { CodeBlock } from '../components/CodeBlock'

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
  const [expanded, setExpanded] = useState<readonly string[]>([])

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
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Tools</h2>
        <p className="text-sm text-[var(--text-muted)] mt-1">Browse tool contracts across all agents. Edit within agent configuration.</p>
      </div>

      {entries.length === 0 ? (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
          <EmptyState message="No tool contracts found." />
        </div>
      ) : (
        <div className="space-y-3">
          {entries.map(entry => {
            const toolNames = parseToolNames(entry.toolsYaml)
            const isOpen = expanded.includes(entry.agentId)
            const preview = toolNames.slice(0, 2).join(', ')
            return (
              <div key={entry.agentId} className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
                <button onClick={() => toggle(entry.agentId)}
                  className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-[var(--bg-hover)] transition-colors">
                  <span className={`text-[var(--text-muted)] transition-transform ${isOpen ? 'rotate-90' : ''}`}>&#9654;</span>
                  <span className="font-medium text-[var(--text-primary)]">{entry.agentName}</span>
                  <span className="text-sm text-[var(--text-secondary)]">{toolNames.length} tools</span>
                  {preview && <span className="text-xs text-[var(--text-muted)] truncate">&mdash; {preview}</span>}
                </button>
                {isOpen && (
                  <div className="px-5 pb-4 space-y-3">
                    <CodeBlock>{entry.toolsYaml}</CodeBlock>
                    <Link to={`/agents/${entry.agentId}/drafts/${entry.draftId}`} className="text-sm text-[var(--accent)] hover:underline">Edit in Agent</Link>
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
