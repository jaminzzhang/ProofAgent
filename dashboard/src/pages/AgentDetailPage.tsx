import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  publishConfigDraft,
  rollbackConfigVersion,
  updateConfigDraft,
  updateConfigDraftContract,
  validateConfigDraft,
} from '../api/client'
import { CodeBlock } from '../components/CodeBlock'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { AgentDetailShell } from '../components/agent/AgentDetailShell'
import { useConfigDraft } from '../hooks/useConfigDraft'
import { useConfigVersions } from '../hooks/useConfigVersions'
import { buildWorkflowNodes, updateAgentYamlField } from '../utils/agentYaml'

type Tab = 'general' | 'workflow' | 'knowledge' | 'tools' | 'policy' | 'model' | 'memory' | 'response' | 'validate' | 'versions' | 'contract' | 'monitor'

export function AgentDetailPage() {
  const { agentId, draftId } = useParams<{ agentId: string; draftId: string }>()
  const { draft, contract, loading, error, refresh } = useConfigDraft(agentId, draftId)
  const {
    versions,
    activeVersionId,
    loading: versionsLoading,
    refresh: refreshVersions,
  } = useConfigVersions(agentId)
  const [activeTab, setActiveTab] = useState<Tab>('general')
  const [displayName, setDisplayName] = useState('')
  const [purpose, setPurpose] = useState('')
  const [agentYaml, setAgentYaml] = useState('')
  const [selectedNodeId, setSelectedNodeId] = useState('workflow')
  const [validationQuestion, setValidationQuestion] = useState('What is the reimbursement rule for travel meals?')
  const [status, setStatus] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    if (draft) {
      setDisplayName(draft.display_name)
      setPurpose(draft.purpose)
    }
  }, [draft])

  useEffect(() => {
    if (contract) setAgentYaml(contract.agent_yaml)
  }, [contract])

  const nodes = useMemo(() => buildWorkflowNodes(agentYaml), [agentYaml])
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? nodes[0]
  const latestValidation = draft?.validation_records[draft.validation_records.length - 1]

  async function runAction(label: string, action: () => Promise<void>) {
    setBusy(label)
    setActionError(null)
    setStatus(null)
    try {
      await action()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  async function saveBasics() {
    if (!agentId || !draftId) return
    await runAction('basics', async () => {
      await updateConfigDraft(agentId, draftId, {
        display_name: displayName,
        purpose,
        actor: 'dashboard',
      })
      setStatus('Draft fields saved.')
      refresh()
    })
  }

  async function saveWorkflow() {
    if (!agentId || !draftId) return
    await runAction('workflow', async () => {
      await updateConfigDraftContract(agentId, draftId, {
        agent_yaml: agentYaml,
        actor: 'dashboard',
      })
      setStatus('Workflow node configuration saved.')
      refresh()
    })
  }

  async function runValidation() {
    if (!agentId || !draftId) return
    await runAction('validation', async () => {
      const result = await validateConfigDraft(agentId, draftId, {
        question: validationQuestion,
        actor: 'dashboard',
      })
      setStatus(`Validation run ${result.run_id} completed with ${result.outcome}.`)
      refresh()
    })
  }

  async function publishDraft() {
    if (!agentId || !draftId || !latestValidation) return
    await runAction('publish', async () => {
      const version = await publishConfigDraft(agentId, draftId, {
        validation_run_id: latestValidation.run_id,
        actor: 'dashboard',
      })
      setStatus(`Published ${version.version_id}.`)
      refreshVersions()
    })
  }

  async function rollback(versionId: string) {
    if (!agentId) return
    await runAction(`rollback-${versionId}`, async () => {
      await rollbackConfigVersion(agentId, versionId, { actor: 'dashboard' })
      setStatus(`Active version set to ${versionId}.`)
      refreshVersions()
    })
  }

  const CONFIGURE_MODULES = [
    { id: 'general', label: 'General' },
    { id: 'workflow', label: 'Workflow' },
    { id: 'knowledge', label: 'Knowledge' },
    { id: 'tools', label: 'Tools' },
    { id: 'policy', label: 'Policy' },
    { id: 'model', label: 'Model' },
    { id: 'memory', label: 'Memory' },
    { id: 'response', label: 'Response' },
  ]

  const LIFECYCLE_TABS = [
    { id: 'validate', label: 'Validate & Test' },
    { id: 'versions', label: 'Versions' },
    { id: 'contract', label: 'Contract View' },
    { id: 'monitor', label: 'Monitor' },
  ]

  if (loading) return <div className="py-12 flex justify-center"><LoadingSpinner /></div>
  if (error) return <div className="text-[var(--danger)] text-sm">{error}</div>
  if (!draft || !contract) return <div className="text-[var(--text-muted)] text-sm">Draft not found.</div>

  return (
    <AgentDetailShell
      agentName={displayName}
      modules={CONFIGURE_MODULES}
      lifecycle={LIFECYCLE_TABS}
      activeModule={activeTab}
      onModuleChange={(moduleId) => setActiveTab(moduleId as Tab)}
    >
      {activeTab === 'general' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <div className="flex items-center justify-between border-b border-[var(--border)] pb-4 mb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              General Configuration
            </h3>
            <button
              onClick={saveBasics}
              disabled={busy === 'basics'}
              className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              {busy === 'basics' ? 'Saving...' : 'Save'}
            </button>
          </div>
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                Display Name
              </label>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                Purpose
              </label>
              <textarea
                value={purpose}
                onChange={(event) => setPurpose(event.target.value)}
                rows={3}
                className="w-full resize-none bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
            <div className="flex gap-2 text-xs font-mono text-[var(--text-muted)]">
              <span>{draft.agent_id}</span>
              <span>•</span>
              <span>{draft.draft_id}</span>
              <span>•</span>
              <span>{draft.validation_records.length} validations</span>
              <span>•</span>
              <span>{versions.length} versions</span>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'workflow' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Workflow Configuration
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Workflow nodes and configuration will be implemented in Phase 4.
          </p>
        </div>
      )}

      {activeTab === 'knowledge' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Knowledge Configuration
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Knowledge providers and bindings will be implemented in Phase 2.
          </p>
        </div>
      )}

      {activeTab === 'tools' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Tools Configuration
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Tool contracts and bindings will be implemented in Phase 2.
          </p>
        </div>
      )}

      {activeTab === 'policy' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Policy Configuration
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Policy rules will be implemented in Phase 2.
          </p>
        </div>
      )}

      {activeTab === 'model' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Model Configuration
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Model providers and roles will be implemented in Phase 2.
          </p>
        </div>
      )}

      {activeTab === 'memory' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Memory Configuration
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Memory providers and scopes will be implemented in Phase 2.
          </p>
        </div>
      )}

      {activeTab === 'response' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Response Configuration
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Response disclosure and language settings will be implemented in Phase 2.
          </p>
        </div>
      )}

      {activeTab === 'validate' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Validate &amp; Test
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Validation workspace will be implemented in Phase 3.
          </p>
        </div>
      )}

      {activeTab === 'versions' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <div className="flex items-center justify-between border-b border-[var(--border)] pb-4">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
                Published Versions
              </h3>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                {activeVersionId ?? 'No active version'}
              </p>
            </div>
            <button
              onClick={publishDraft}
              disabled={busy === 'publish' || !latestValidation}
              className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              Publish
            </button>
          </div>
          {versionsLoading ? (
            <div className="py-8 flex justify-center"><LoadingSpinner size="sm" /></div>
          ) : versions.length === 0 ? (
            <EmptyState message="No published versions." />
          ) : (
            <div className="mt-4 divide-y divide-[var(--border)]">
              {versions.map((version) => (
                <div key={version.version_id} className="flex items-center justify-between gap-4 py-3">
                  <div>
                    <div className="font-mono text-xs text-[var(--text-primary)]">{version.version_id}</div>
                    <div className="mt-1 text-xs text-[var(--text-muted)]">validated by {version.validation_run_id}</div>
                  </div>
                  {version.version_id === activeVersionId ? (
                    <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)]">
                      Active
                    </span>
                  ) : (
                    <button
                      onClick={() => rollback(version.version_id)}
                      disabled={busy === `rollback-${version.version_id}`}
                      className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                    >
                      Rollback
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'contract' && (
        <div className="grid gap-5">
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">agent.yaml</h3>
            <CodeBlock>{agentYaml}</CodeBlock>
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">policy.yaml</h3>
            <CodeBlock>{contract.policy_yaml}</CodeBlock>
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">tools.yaml</h3>
            <CodeBlock>{contract.tools_yaml}</CodeBlock>
          </section>
        </div>
      )}

      {activeTab === 'monitor' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Agent Monitoring
          </h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Recent runs, success rate, and validation history will be implemented in Phase 3.
          </p>
        </div>
      )}

      {(status || actionError) && (
        <div className={`fixed bottom-4 right-4 rounded-md border px-4 py-3 text-sm shadow-lg ${
          actionError
            ? 'border-[var(--danger)]/40 bg-[var(--danger)]/10 text-[var(--danger)]'
            : 'border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)]'
        }`}>
          {actionError ?? status}
        </div>
      )}
    </AgentDetailShell>
  )
}
