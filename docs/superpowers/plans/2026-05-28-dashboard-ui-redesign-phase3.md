# Dashboard UI Redesign - Phase 3: Validation & Monitoring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Replace the Validate & Test and Monitor placeholder tabs with working components — a validation workspace for running test questions and reviewing results, and an agent-specific monitoring view for recent runs and stats.

**Architecture:** ValidateWorkspace uses the existing `validateConfigDraft` API and `draft.validation_records` for history. AgentMonitor filters global runs by `agent_id` client-side. Both are self-contained components wired into AgentDetailPage.

**Tech Stack:** React, TypeScript, Tailwind CSS, existing API client

---

## Task 1: ValidateWorkspace Component

**Files:**
- Create: `dashboard/src/components/agent/ValidateWorkspace.tsx`

```typescript
// dashboard/src/components/agent/ValidateWorkspace.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { AgentValidationRecord } from '../../api/types'
import { EmptyState } from '../EmptyState'
import { OutcomeBadge } from '../OutcomeBadge'

interface ValidateWorkspaceProps {
  agentId: string
  draftId: string
  validationRecords: AgentValidationRecord[]
  onValidate: (question: string) => Promise<void>
  busy: boolean
}

export function ValidateWorkspace({
  agentId,
  draftId,
  validationRecords,
  onValidate,
  busy,
}: ValidateWorkspaceProps) {
  const [question, setQuestion] = useState('')
  const [activeTab, setActiveTab] = useState<'quick' | 'history'>('quick')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    await onValidate(question.trim())
    setQuestion('')
  }

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex gap-4 border-b border-[var(--border)]">
        {(['quick', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-1 py-3 text-sm font-medium tracking-wide border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-[var(--accent)] text-[var(--text-primary)]'
                : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--text-muted)]'
            }`}
          >
            {tab === 'quick' ? 'Quick Test' : `History (${validationRecords.length})`}
          </button>
        ))}
      </div>

      {/* Quick Test */}
      {activeTab === 'quick' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
          <form onSubmit={handleSubmit} className="flex gap-3">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Enter a test question..."
              className="flex-1 bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
            />
            <button
              type="submit"
              disabled={busy || !question.trim()}
              className="shrink-0 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90 disabled:opacity-50"
            >
              {busy ? 'Running...' : 'Run Test'}
            </button>
          </form>

          {/* Inline result preview */}
          {validationRecords.length > 0 && (
            <div className="mt-4 border border-[var(--border)] rounded-md overflow-hidden">
              <ValidationRecordRow record={validationRecords[validationRecords.length - 1]} />
            </div>
          )}
        </div>
      )}

      {/* History */}
      {activeTab === 'history' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
          {validationRecords.length === 0 ? (
            <EmptyState message="No validation runs yet. Run a quick test to get started." />
          ) : (
            <div className="divide-y divide-[var(--border)]">
              {validationRecords.map((record) => (
                <ValidationRecordRow key={record.validation_id} record={record} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ValidationRecordRow({ record }: { record: AgentValidationRecord }) {
  return (
    <div className="px-4 py-3 flex items-center gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {record.status === 'completed' ? '✓' : '○'}
          </span>
          <Link
            to={`/runs/${record.run_id}`}
            className="font-mono text-xs text-[var(--accent)] hover:underline truncate"
          >
            {record.run_id}
          </Link>
        </div>
        {record.summary && (
          <p className="mt-1 text-xs text-[var(--text-muted)] line-clamp-2">{record.summary}</p>
        )}
        {record.errors.length > 0 && (
          <div className="mt-1 text-xs text-[var(--danger)]">
            {record.errors.slice(0, 2).map((err, i) => (
              <div key={i}>{err}</div>
            ))}
          </div>
        )}
      </div>
      <span className="text-xs text-[var(--text-muted)] shrink-0">
        {new Date(record.created_at).toLocaleString()}
      </span>
    </div>
  )
}
```

- [ ] Commit: `git add ... && git commit -m "feat: add ValidateWorkspace component"`

---

## Task 2: AgentMonitor Component

**Files:**
- Create: `dashboard/src/components/agent/AgentMonitor.tsx`

```typescript
// dashboard/src/components/agent/AgentMonitor.tsx
import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { fetchRuns } from '../../api/client'
import type { RunSummary, ReceiptOutcome } from '../../api/types'
import { OutcomeBadge } from '../OutcomeBadge'
import { EmptyState } from '../EmptyState'
import { LoadingSpinner } from '../ui/LoadingSpinner'

interface AgentMonitorProps {
  agentId: string
}

export function AgentMonitor({ agentId }: AgentMonitorProps) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchRuns({ limit: 50 })
      .then((data) => setRuns(data.data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const agentRuns = useMemo(
    () => runs.filter((run) => run.agent_id === agentId),
    [runs, agentId],
  )

  const productionRuns = useMemo(
    () => agentRuns.filter((r) => r.run_purpose === 'production'),
    [agentRuns],
  )

  const validationRuns = useMemo(
    () => agentRuns.filter((r) => r.run_purpose === 'validation'),
    [agentRuns],
  )

  const stats = useMemo(() => {
    const outcomeCounts: Record<string, number> = {}
    for (const run of productionRuns) {
      outcomeCounts[run.outcome] = (outcomeCounts[run.outcome] || 0) + 1
    }
    const answered = outcomeCounts['ANSWERED_WITH_CITATIONS'] || 0
    const total = productionRuns.length
    const answerRate = total > 0 ? Math.round((answered / total) * 100) : 0
    return { outcomeCounts, answered, total, answerRate }
  }, [productionRuns])

  if (loading) return <div className="py-12 flex justify-center"><LoadingSpinner /></div>
  if (error) return <div className="text-[var(--danger)] text-sm">{error}</div>

  return (
    <div className="space-y-6">
      {/* Stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="Total Runs" value={String(stats.total)} subtitle="All production runs" />
        <StatCard label="Answered Rate" value={`${stats.answerRate}%`} subtitle="With citations" />
        <StatCard label="Validations" value={String(validationRuns.length)} subtitle="Test runs" />
      </div>

      {/* Outcome distribution */}
      {stats.total > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
            Outcome Distribution
          </h3>
          <div className="flex flex-wrap gap-3">
            {Object.entries(stats.outcomeCounts).map(([outcome, count]) => (
              <span key={outcome} className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                <OutcomeBadge outcome={outcome as ReceiptOutcome} />
                <span>{count}</span>
                <span className="text-[var(--text-muted)]">
                  ({Math.round((count / stats.total) * 100)}%)
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Recent runs */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
        <div className="px-5 py-3 border-b border-[var(--border)] bg-[var(--bg-elevated)]">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Recent Runs
          </h3>
        </div>
        {agentRuns.length === 0 ? (
          <EmptyState message="No runs for this agent yet." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Question</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Outcome</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Purpose</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {agentRuns.slice(0, 20).map((run) => (
                <tr key={run.run_id} className="hover:bg-[var(--bg-hover)] transition-colors">
                  <td className="px-5 py-3">
                    <Link to={`/runs/${run.run_id}`} className="text-[var(--text-primary)] hover:text-[var(--accent)] font-medium truncate block max-w-xs">
                      {run.question}
                    </Link>
                  </td>
                  <td className="px-5 py-3">
                    <OutcomeBadge outcome={run.outcome} />
                  </td>
                  <td className="px-5 py-3 text-xs text-[var(--text-muted)]">{run.run_purpose}</td>
                  <td className="px-5 py-3 text-xs text-[var(--text-muted)] font-mono">
                    {new Date(run.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function StatCard({ label, value, subtitle }: { label: string; value: string; subtitle: string }) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">{value}</div>
      <div className="mt-1 text-xs text-[var(--text-muted)]">{subtitle}</div>
    </div>
  )
}
```

- [ ] Commit: `git add ... && git commit -m "feat: add AgentMonitor component"`

---

## Task 3: Wire into AgentDetailPage

**Files:**
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`

Add imports:
```typescript
import { ValidateWorkspace } from '../components/agent/ValidateWorkspace'
import { AgentMonitor } from '../components/AgentMonitor'
```

Replace the validate placeholder:
```tsx
{activeTab === 'validate' && (
  <ValidateWorkspace
    agentId={agentId!}
    draftId={draftId!}
    validationRecords={draft.validation_records}
    onValidate={async (question) => {
      await runAction('validation', async () => {
        const result = await validateConfigDraft(agentId!, draftId!, {
          question,
          actor: 'dashboard',
        })
        setStatus(`Validation run ${result.run_id} completed with ${result.outcome}.`)
        refresh()
      })
    }}
    busy={busy === 'validation'}
  />
)}
```

Replace the monitor placeholder:
```tsx
{activeTab === 'monitor' && (
  <AgentMonitor agentId={agentId!} />
)}
```

- [ ] TypeScript check
- [ ] Commit: `git add ... && git commit -m "feat: wire ValidateWorkspace and AgentMonitor into AgentDetailPage"`

---

## Task 4: Verification

- [ ] Run all tests: `cd dashboard && npx vitest run`
- [ ] TypeScript check: `cd dashboard && npx tsc --noEmit`
- [ ] Commit plan doc: `git add docs/superpowers/plans/2026-05-28-dashboard-ui-redesign-phase3.md && git commit -m "docs: add Phase 3 plan"`
