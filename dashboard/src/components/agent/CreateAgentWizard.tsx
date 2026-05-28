import { useState } from 'react'
import type { DraftAgent } from '../../api/types'

interface Template {
  readonly id: string
  readonly name: string
  readonly purpose: string
  readonly manifestPath: string
  readonly description: string
}

const TEMPLATES: readonly Template[] = [
  { id: 'react_enterprise_qa', name: 'ReAct Enterprise QA', purpose: 'Answer enterprise knowledge questions through a governed ReAct workflow.', manifestPath: 'examples/react_enterprise_qa/agent.yaml', description: 'ReAct loop with planner, evidence retrieval, policy-gated response generation.' },
  { id: 'enterprise_qa', name: 'Enterprise QA', purpose: 'Answer enterprise knowledge questions only when evidence supports the answer.', manifestPath: 'examples/enterprise_qa/agent.yaml', description: 'Single-pass evidence retrieval and answer generation.' },
  { id: 'insurance_customer_service', name: 'Insurance Customer Service', purpose: 'Provide read-only customer service for insurance policy and claim questions.', manifestPath: 'examples/insurance_customer_service/agent.yaml', description: 'Customer-facing insurance Q&A with account-scoped evidence.' },
  { id: 'insurance_service_qa', name: 'Insurance Service QA', purpose: 'Assist service staff with insurance policy and claim questions.', manifestPath: 'examples/insurance_service_qa/agent.yaml', description: 'Internal staff Q&A with policy evidence and governance.' },
]

type Step = 'template' | 'details'

interface WizardState {
  readonly step: Step
  readonly selectedTemplate: Template | null
  readonly displayName: string
  readonly purpose: string
  readonly loading: boolean
  readonly error: string | null
}

const INITIAL_STATE: WizardState = {
  step: 'template', selectedTemplate: null, displayName: '', purpose: '', loading: false, error: null,
}

interface CreateAgentWizardProps {
  open: boolean
  onClose: () => void
  onCreated: (agent: DraftAgent) => void
  onCreate: (manifestPath: string, displayName: string, purpose: string) => Promise<DraftAgent>
}

export function CreateAgentWizard({ open, onClose, onCreated, onCreate }: CreateAgentWizardProps) {
  const [state, setState] = useState<WizardState>(INITIAL_STATE)
  if (!open) return null

  const resetAndClose = () => { setState(INITIAL_STATE); onClose() }
  const handleBackdrop = (e: React.MouseEvent<HTMLDivElement>) => { if (e.target === e.currentTarget) resetAndClose() }

  const selectTemplate = (t: Template) => {
    setState({ ...INITIAL_STATE, step: 'details', selectedTemplate: t, displayName: t.name, purpose: t.purpose })
  }

  const handleCreate = async () => {
    if (!state.selectedTemplate || !state.displayName.trim()) return
    setState((p) => ({ ...p, loading: true, error: null }))
    try {
      const agent = await onCreate(state.selectedTemplate.manifestPath, state.displayName.trim(), state.purpose.trim())
      onCreated(agent)
      resetAndClose()
    } catch (err: unknown) {
      setState((p) => ({ ...p, loading: false, error: err instanceof Error ? err.message : 'Failed to create agent' }))
    }
  }

  const stepClass = (s: Step) => state.step === s ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'
  const inputCls = 'w-full rounded border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] focus:outline-none'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={handleBackdrop}>
      <div className="w-full max-w-xl rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] shadow-xl" onClick={(e) => e.stopPropagation()}>
        {/* Header + step indicator */}
        <div className="border-b border-[var(--border)] px-6 py-4">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">Create Agent</h2>
          <div className="mt-3 flex items-center gap-2 text-xs font-medium">
            <span className={stepClass('template')}>
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-current text-[10px]">1</span> Template
            </span>
            <span className="text-[var(--text-muted)]">&rarr;</span>
            <span className={stepClass('details')}>
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-current text-[10px]">2</span> Details
            </span>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          {state.error && (
            <div className="mb-4 rounded border border-[var(--danger)] bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
              {state.error}
            </div>
          )}

          {state.step === 'template' && (
            <div className="grid grid-cols-2 gap-3">
              {TEMPLATES.map((t) => (
                <button key={t.id} type="button" onClick={() => selectTemplate(t)}
                  className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4 text-left transition-colors hover:border-[var(--accent)] hover:bg-[var(--bg-hover)]">
                  <div className="text-sm font-semibold text-[var(--text-primary)]">{t.name}</div>
                  <div className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">{t.description}</div>
                </button>
              ))}
            </div>
          )}

          {state.step === 'details' && state.selectedTemplate && (
            <div className="space-y-4">
              <div className="flex items-center justify-between rounded border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-xs text-[var(--text-secondary)]">
                <span>Template: <strong className="text-[var(--text-primary)]">{state.selectedTemplate.name}</strong></span>
                <button type="button" className="text-[var(--accent)] hover:underline"
                  onClick={() => setState((p) => ({ ...p, step: 'template', error: null }))}>Change</button>
              </div>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">
                  Display Name <span className="text-[var(--danger)]">*</span>
                </span>
                <input type="text" value={state.displayName}
                  onChange={(e) => setState((p) => ({ ...p, displayName: e.target.value }))}
                  className={inputCls} placeholder="My Agent" />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">Purpose</span>
                <textarea value={state.purpose}
                  onChange={(e) => setState((p) => ({ ...p, purpose: e.target.value }))}
                  rows={3} className={`${inputCls} resize-none`} placeholder="What this agent does..." />
              </label>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-[var(--border)] px-6 py-3">
          <button type="button" className="rounded px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors" onClick={resetAndClose}>
            Cancel
          </button>
          {state.step === 'details' && (
            <button type="button" disabled={!state.displayName.trim() || state.loading} onClick={handleCreate}
              className="rounded bg-[var(--accent)] px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 transition-opacity">
              {state.loading ? 'Creating...' : 'Create Agent'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
