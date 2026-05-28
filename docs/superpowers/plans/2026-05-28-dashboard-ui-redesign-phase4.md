# Dashboard UI Redesign - Phase 4: Agent Creation Wizard & Workflow Accordion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Add an Agent Creation Wizard (modal with template selection → name/purpose → import) to replace the static "+ Create Agent" button, and upgrade the Workflow tab from a flat form to an accordion-style node editor that visualizes the agent pipeline.

**Architecture:** CreateAgentWizard is a modal dialog triggered from AgentsPage. It offers 4 template presets, collects name + purpose, and calls the existing `importConfigAgent` API. WorkflowAccordion replaces the ModuleEditor on the workflow tab with an expandable node list using the existing `buildWorkflowNodes` utility.

**Tech Stack:** React, TypeScript, Tailwind CSS, existing API client + agentYaml utils

---

## Task 1: CreateAgentWizard Component

**Files:**
- Create: `dashboard/src/components/agent/CreateAgentWizard.tsx`

```typescript
// dashboard/src/components/agent/CreateAgentWizard.tsx
import { useState } from 'react'
import type { DraftAgent } from '../../api/types'

interface AgentTemplate {
  id: string
  name: string
  purpose: string
  manifestPath: string
  description: string
}

const TEMPLATES: AgentTemplate[] = [
  {
    id: 'react_enterprise_qa',
    name: 'ReAct Enterprise QA',
    purpose: 'Answer enterprise knowledge questions through a governed ReAct workflow.',
    manifestPath: 'examples/react_enterprise_qa/agent.yaml',
    description: 'ReAct loop with planner, evidence retrieval, policy-gated response generation.',
  },
  {
    id: 'enterprise_qa',
    name: 'Enterprise QA',
    purpose: 'Answer enterprise knowledge questions only when evidence supports the answer.',
    manifestPath: 'examples/enterprise_qa/agent.yaml',
    description: 'Single-pass evidence retrieval and answer generation.',
  },
  {
    id: 'insurance_customer_service',
    name: 'Insurance Customer Service',
    purpose: 'Provide read-only customer service for insurance policy and claim questions.',
    manifestPath: 'examples/insurance_customer_service/agent.yaml',
    description: 'Customer-facing insurance Q&A with account-scoped evidence.',
  },
  {
    id: 'insurance_service_qa',
    name: 'Insurance Service QA',
    purpose: 'Assist service staff with insurance policy and claim questions.',
    manifestPath: 'examples/insurance_service_qa/agent.yaml',
    description: 'Internal staff Q&A with policy evidence and governance.',
  },
]

interface CreateAgentWizardProps {
  open: boolean
  onClose: () => void
  onCreated: (agent: DraftAgent) => void
  onCreate: (manifestPath: string, displayName: string, purpose: string) => Promise<DraftAgent>
}

type Step = 'template' | 'details'

export function CreateAgentWizard({ open, onClose, onCreated, onCreate }: CreateAgentWizardProps) {
  const [step, setStep] = useState<Step>('template')
  const [selectedTemplate, setSelectedTemplate] = useState<AgentTemplate | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [purpose, setPurpose] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  function handleSelectTemplate(template: AgentTemplate) {
    setSelectedTemplate(template)
    setDisplayName(template.name)
    setPurpose(template.purpose)
    setStep('details')
  }

  function handleBack() {
    setStep('template')
    setError(null)
  }

  async function handleCreate() {
    if (!selectedTemplate || !displayName.trim()) return
    setCreating(true)
    setError(null)
    try {
      const agent = await onCreate(selectedTemplate.manifestPath, displayName.trim(), purpose.trim())
      onCreated(agent)
      handleClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  function handleClose() {
    setStep('template')
    setSelectedTemplate(null)
    setDisplayName('')
    setPurpose('')
    setError(null)
    setCreating(false)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={handleClose}>
      <div
        className="w-full max-w-2xl bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border)] px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-[var(--text-primary)]">Create Agent</h2>
            <p className="text-sm text-[var(--text-muted)] mt-0.5">
              {step === 'template' ? 'Choose a template to get started' : 'Name and describe your agent'}
            </p>
          </div>
          <button onClick={handleClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 px-6 pt-4">
          <StepDot active={step === 'template'} done={step === 'details'} label="Template" />
          <div className="h-px flex-1 bg-[var(--border)]" />
          <StepDot active={step === 'details'} done={false} label="Details" />
        </div>

        {/* Template selection */}
        {step === 'template' && (
          <div className="p-6 grid gap-3 sm:grid-cols-2">
            {TEMPLATES.map((template) => (
              <button
                key={template.id}
                onClick={() => handleSelectTemplate(template)}
                className={`text-left p-4 rounded-lg border transition-colors ${
                  selectedTemplate?.id === template.id
                    ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                    : 'border-[var(--border)] hover:border-[var(--text-muted)] bg-[var(--bg-base)]'
                }`}
              >
                <div className="text-sm font-medium text-[var(--text-primary)]">{template.name}</div>
                <div className="mt-1 text-xs text-[var(--text-muted)] line-clamp-2">{template.description}</div>
              </button>
            ))}
          </div>
        )}

        {/* Details form */}
        {step === 'details' && selectedTemplate && (
          <div className="p-6 space-y-4">
            <div className="rounded-md bg-[var(--bg-base)] border border-[var(--border)] p-3 flex items-center gap-3">
              <span className="text-xs font-medium text-[var(--text-muted)] uppercase">Template</span>
              <span className="text-sm text-[var(--text-primary)]">{selectedTemplate.name}</span>
              <button onClick={handleBack} className="ml-auto text-xs text-[var(--accent)] hover:underline">
                Change
              </button>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                Display Name *
              </label>
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="My Agent"
                className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                Purpose
              </label>
              <textarea
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                rows={3}
                placeholder="What does this agent do?"
                className="w-full resize-none bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            {error && (
              <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
                {error}
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-[var(--border)] px-6 py-4">
          <button
            onClick={handleClose}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
          >
            Cancel
          </button>
          {step === 'details' && (
            <button
              onClick={handleCreate}
              disabled={creating || !displayName.trim()}
              className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90 disabled:opacity-50"
            >
              {creating ? 'Creating...' : 'Create Agent'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function StepDot({ active, done, label }: { active: boolean; done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={`w-2 h-2 rounded-full ${
          done ? 'bg-[var(--accent)]' : active ? 'bg-[var(--text-primary)]' : 'bg-[var(--text-muted)]'
        }`}
      />
      <span className={`text-xs font-medium ${active ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}>
        {label}
      </span>
    </div>
  )
}
```

- [ ] Commit: `git add ... && git commit -m "feat: add CreateAgentWizard modal component"`

---

## Task 2: Wire CreateAgentWizard into AgentsPage

**Files:**
- Modify: `dashboard/src/pages/AgentsPage.tsx`

Add state for wizard open/close:
```typescript
const [wizardOpen, setWizardOpen] = useState(false)
```

Replace the static "+ Create Agent" button:
```tsx
<button
  onClick={() => setWizardOpen(true)}
  className="shrink-0 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90"
>
  + Create Agent
</button>
```

Add wizard component before the closing `</div>`:
```tsx
<CreateAgentWizard
  open={wizardOpen}
  onClose={() => setWizardOpen(false)}
  onCreated={() => refresh()}
  onCreate={async (manifestPath, displayName, purpose) => {
    const agent = await importConfigAgent({ manifest_path: manifestPath, actor: 'dashboard' })
    if (displayName || purpose) {
      await updateConfigDraft(agent.agent_id, agent.draft_id, {
        display_name: displayName || undefined,
        purpose: purpose || undefined,
        actor: 'dashboard',
      })
    }
    return agent
  }}
/>
```

Add imports:
```typescript
import { CreateAgentWizard } from '../components/agent/CreateAgentWizard'
import { importConfigAgent, updateConfigDraft } from '../api/client'
```

- [ ] Commit: `git add ... && git commit -m "feat: wire CreateAgentWizard into AgentsPage"`

---

## Task 3: WorkflowAccordion Component

**Files:**
- Create: `dashboard/src/components/agent/WorkflowAccordion.tsx`

```typescript
// dashboard/src/components/agent/WorkflowAccordion.tsx
import { useState } from 'react'
import type { WorkflowNodeConfig } from '../../utils/agentYaml'

interface WorkflowAccordionProps {
  nodes: WorkflowNodeConfig[]
  selectedNodeId: string
  onSelectNode: (nodeId: string) => void
  onFieldChange: (nodeId: string, path: string[], value: string) => void
}

export function WorkflowAccordion({
  nodes,
  selectedNodeId,
  onSelectNode,
  onFieldChange,
}: WorkflowAccordionProps) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
      {/* Pipeline visualization header */}
      <div className="px-5 py-4 border-b border-[var(--border)] bg-[var(--bg-elevated)]">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Agent Pipeline
        </h3>
        <div className="mt-3 flex items-center gap-1 overflow-x-auto">
          {nodes.map((node, index) => (
            <div key={node.id} className="flex items-center">
              <button
                onClick={() => onSelectNode(node.id)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors ${
                  selectedNodeId === node.id
                    ? 'bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30'
                    : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] border border-transparent'
                }`}
              >
                {node.label}
              </button>
              {index < nodes.length - 1 && (
                <svg className="w-4 h-4 text-[var(--text-muted)] shrink-0" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M6 4l4 4-4 4" />
                </svg>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Expanded node editor */}
      {nodes.map((node) => (
        <NodeEditor
          key={node.id}
          node={node}
          expanded={selectedNodeId === node.id}
          onToggle={() => onSelectNode(selectedNodeId === node.id ? '' : node.id)}
          onFieldChange={(path, value) => onFieldChange(node.id, path, value)}
        />
      ))}
    </div>
  )
}

interface NodeEditorProps {
  node: WorkflowNodeConfig
  expanded: boolean
  onToggle: () => void
  onFieldChange: (path: string[], value: string) => void
}

function NodeEditor({ node, expanded, onToggle, onFieldChange }: NodeEditorProps) {
  return (
    <div className={expanded ? 'bg-[var(--bg-base)]' : ''}>
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 py-3 border-b border-[var(--border)] hover:bg-[var(--bg-hover)] transition-colors"
      >
        <div className="flex items-center gap-3">
          <svg
            className={`w-3 h-3 text-[var(--text-muted)] transition-transform ${expanded ? 'rotate-90' : ''}`}
            viewBox="0 0 12 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M4 2l4 4-4 4" />
          </svg>
          <span className="text-sm font-medium text-[var(--text-primary)]">{node.label}</span>
        </div>
        <div className="flex items-center gap-2">
          {node.fields.slice(0, 2).map((field) => (
            <span key={field.path.join('.')} className="text-xs text-[var(--text-muted)] font-mono">
              {field.value || '—'}
            </span>
          ))}
        </div>
      </button>

      {expanded && (
        <div className="px-5 py-4 border-b border-[var(--border)] space-y-3">
          {node.fields.map((field) => (
            <div key={field.path.join('.')} className="flex items-center gap-4">
              <label className="w-36 shrink-0 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {field.label}
              </label>
              <input
                type={field.input}
                value={field.value}
                onChange={(e) => onFieldChange(field.path, e.target.value)}
                className="flex-1 bg-[var(--bg-surface)] border border-[var(--border)] rounded-md px-3 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] Commit: `git add ... && git commit -m "feat: add WorkflowAccordion component with pipeline visualization"`

---

## Task 4: Wire WorkflowAccordion into AgentDetailPage

**Files:**
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`

Add import:
```typescript
import { WorkflowAccordion } from '../components/agent/WorkflowAccordion'
```

Replace the workflow tab content (currently using ModuleEditor):
```tsx
{activeTab === 'workflow' && (
  <WorkflowAccordion
    nodes={nodes}
    selectedNodeId={selectedNodeId}
    onSelectNode={setSelectedNodeId}
    onFieldChange={(_nodeId, path, value) =>
      setAgentYaml((current) => updateAgentYamlField(current, path, value))
    }
  />
)}
```

Also add a Save button bar below the accordion:
```tsx
{activeTab === 'workflow' && (
  <div className="space-y-4">
    <WorkflowAccordion
      nodes={nodes}
      selectedNodeId={selectedNodeId}
      onSelectNode={setSelectedNodeId}
      onFieldChange={(_nodeId, path, value) =>
        setAgentYaml((current) => updateAgentYamlField(current, path, value))
      }
    />
    <div className="flex justify-end">
      <button
        onClick={saveWorkflow}
        disabled={busy === 'workflow'}
        className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
      >
        {busy === 'workflow' ? 'Saving...' : 'Save Workflow'}
      </button>
    </div>
  </div>
)}
```

- [ ] TypeScript check
- [ ] Commit: `git add ... && git commit -m "feat: replace flat workflow editor with WorkflowAccordion"`

---

## Task 5: Verification

- [ ] Run all tests: `cd dashboard && npx vitest run`
- [ ] TypeScript check: `cd dashboard && npx tsc --noEmit`
- [ ] Commit plan doc: `git add docs/superpowers/plans/2026-05-28-dashboard-ui-redesign-phase4.md && git commit -m "docs: add Phase 4 plan"`
