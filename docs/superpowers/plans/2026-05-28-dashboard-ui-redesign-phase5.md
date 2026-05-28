# Dashboard UI Redesign - Phase 5: Shared Asset Library Pages

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Replace the 3 placeholder sidebar links (Policies, Knowledge, Tools) with real list pages that browse shared assets from agent contract bundles. Each page shows a table of assets with preview capabilities.

**Architecture:** Three new pages (PoliciesPage, KnowledgePage, ToolsPage) each fetch all agents via `fetchConfigAgents`, then fetch each agent's contract to extract the relevant YAML section. Pages are read-only browsers — editing happens inside AgentDetailPage. Add routes in `router.tsx` and update sidebar links.

**Tech Stack:** React, TypeScript, Tailwind CSS, existing API client

---

## Task 1: PoliciesPage

**Files:**
- Create: `dashboard/src/pages/PoliciesPage.tsx`

```typescript
// dashboard/src/pages/PoliciesPage.tsx
import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { fetchConfigAgents, fetchConfigDraftContract } from '../api/client'
import type { ConfigAgentSummary, ContractBundle } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { CodeBlock } from '../components/CodeBlock'

interface PolicyEntry {
  agentId: string
  agentName: string
  draftId: string
  policyYaml: string
}

export function PoliciesPage() {
  const [entries, setEntries] = useState<PolicyEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const agentsResp = await fetchConfigAgents()
        const results: PolicyEntry[] = []
        for (const agent of agentsResp.data) {
          if (!agent.latest_draft_id) continue
          try {
            const contract = await fetchConfigDraftContract(agent.agent_id, agent.latest_draft_id)
            if (contract.policy_yaml.trim()) {
              results.push({
                agentId: agent.agent_id,
                agentName: agent.display_name,
                draftId: agent.latest_draft_id,
                policyYaml: contract.policy_yaml,
              })
            }
          } catch { /* skip agents with missing contracts */ }
        }
        setEntries(results)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) return <div className="py-12 flex justify-center"><LoadingSpinner /></div>
  if (error) return <div className="text-[var(--danger)] text-sm">{error}</div>

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Policies</h2>
        <p className="text-sm text-[var(--text-muted)] mt-1">Browse governance policies across all agents. Edit within agent configuration.</p>
      </div>

      {entries.length === 0 ? (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
          <EmptyState message="No policies found. Configure agents to add policies." />
        </div>
      ) : (
        <div className="space-y-3">
          {entries.map((entry) => (
            <div key={entry.agentId} className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
              <button
                onClick={() => setExpandedId(expandedId === entry.agentId ? null : entry.agentId)}
                className="w-full flex items-center justify-between px-5 py-4 hover:bg-[var(--bg-hover)] transition-colors"
              >
                <div className="flex items-center gap-3">
                  <svg
                    className={`w-3 h-3 text-[var(--text-muted)] transition-transform ${expandedId === entry.agentId ? 'rotate-90' : ''}`}
                    viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"
                  >
                    <path d="M4 2l4 4-4 4" />
                  </svg>
                  <div className="text-left">
                    <div className="text-sm font-medium text-[var(--text-primary)]">{entry.agentName}</div>
                    <div className="text-xs text-[var(--text-muted)] mt-0.5">
                      {entry.policyYaml.split('\n').filter(l => l.trim().startsWith('- rule_id:')).length} rules
                    </div>
                  </div>
                </div>
                <Link
                  to={`/agents/${entry.agentId}/drafts/${entry.draftId}`}
                  onClick={(e) => e.stopPropagation()}
                  className="text-xs text-[var(--accent)] hover:underline"
                >
                  Edit in Agent
                </Link>
              </button>
              {expandedId === entry.agentId && (
                <div className="border-t border-[var(--border)] p-5">
                  <CodeBlock>{entry.policyYaml}</CodeBlock>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] Commit: `git add ... && git commit -m "feat: add PoliciesPage with collapsible policy browser"`

---

## Task 2: ToolsPage

**Files:**
- Create: `dashboard/src/pages/ToolsPage.tsx`

Same structure as PoliciesPage but for `tools_yaml`. Parse tool names from YAML for preview.

```typescript
// Parse tool names: lines matching "  - name: <value>"
const toolNames = entry.toolsYaml.split('\n')
  .filter(l => l.trim().startsWith('- name:'))
  .map(l => l.replace(/.*- name:\s*['"]?/, '').replace(/['"]\s*$/, ''))
```

Show tool count and names in the collapsed row instead of rule count.

- [ ] Commit: `git add ... && git commit -m "feat: add ToolsPage with collapsible tools browser"`

---

## Task 3: KnowledgePage

**Files:**
- Create: `dashboard/src/pages/KnowledgePage.tsx`

Same structure but for `agent_yaml` knowledge section. Parse provider and path for preview.

```typescript
// Parse knowledge provider from agent_yaml
const providerLine = agentYaml.split('\n').find(l => /^  provider:/.test(l))
const pathLine = agentYaml.split('\n').find(l => /^    path:/.test(l))
```

Show provider name and path in the collapsed row.

- [ ] Commit: `git add ... && git commit -m "feat: add KnowledgePage with collapsible knowledge browser"`

---

## Task 4: Add Routes + Update Sidebar

**Files:**
- Modify: `dashboard/src/router.tsx`
- Modify: `dashboard/src/components/Sidebar.tsx`

Add 3 routes:
```typescript
import { PoliciesPage } from './pages/PoliciesPage'
import { ToolsPage } from './pages/ToolsPage'
import { KnowledgePage } from './pages/KnowledgePage'

<Route path="/policies" element={<PoliciesPage />} />
<Route path="/tools" element={<ToolsPage />} />
<Route path="/knowledge" element={<KnowledgePage />} />
```

Update Sidebar links from `#policies` → `/policies`, `#knowledge` → `/knowledge`, `#tools` → `/tools`.

- [ ] Commit: `git add ... && git commit -m "feat: add shared asset library routes and sidebar links"`

---

## Task 5: Verification

- [ ] Run all tests: `cd dashboard && npx vitest run`
- [ ] TypeScript check: `cd dashboard && npx tsc --noEmit`
- [ ] Commit plan doc: `git add docs/superpowers/plans/2026-05-28-dashboard-ui-redesign-phase5.md && git commit -m "docs: add Phase 5 plan"`
