import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
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
import { useConfigDraft } from '../hooks/useConfigDraft'
import { useConfigVersions } from '../hooks/useConfigVersions'
import { buildWorkflowNodes, updateAgentYamlField } from '../utils/agentYaml'

type Tab = 'workflow' | 'contract' | 'validation' | 'versions'

export function AgentDetailPage() {
  const { agentId, draftId } = useParams<{ agentId: string; draftId: string }>()
  const { draft, contract, loading, error, refresh } = useConfigDraft(agentId, draftId)
  const {
    versions,
    activeVersionId,
    loading: versionsLoading,
    refresh: refreshVersions,
  } = useConfigVersions(agentId)
  const [activeTab, setActiveTab] = useState<Tab>('workflow')
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

  if (loading) return <div className="py-12 flex justify-center"><LoadingSpinner /></div>
  if (error) return <div className="text-[var(--danger)] text-sm">{error}</div>
  if (!draft || !contract) return <div className="text-[var(--text-muted)] text-sm">Draft not found.</div>

  return (
    <div className="w-full min-w-0 max-w-6xl space-y-6 overflow-hidden">
      <div className="min-w-0 bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <Link to="/agents" className="text-xs font-medium tracking-wide text-[var(--text-muted)] hover:text-[var(--text-primary)] uppercase">
          &larr; Back to Agents
        </Link>
        <div className="mt-4 grid min-w-0 gap-4 md:grid-cols-[1fr_2fr_auto] md:items-start">
          <div className="min-w-0">
            <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">Display Name</label>
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div className="min-w-0">
            <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">Purpose</label>
            <textarea
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
              rows={2}
              className="w-full resize-none bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          <button
            onClick={saveBasics}
            disabled={busy === 'basics'}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50 md:mt-6"
          >
            Save
          </button>
        </div>
        <div className="mt-4 grid gap-2 text-xs font-mono text-[var(--text-muted)] sm:flex sm:flex-wrap sm:gap-3">
          <span>{draft.agent_id}</span>
          <span>{draft.draft_id}</span>
          <span>{draft.validation_records.length} validations</span>
          <span>{versions.length} versions</span>
        </div>
      </div>

      {(status || actionError) && (
        <div className={`rounded-md border px-4 py-3 text-sm ${
          actionError
            ? 'border-[var(--danger)]/40 bg-[var(--danger)]/10 text-[var(--danger)]'
            : 'border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)]'
        }`}>
          {actionError ?? status}
        </div>
      )}

      <div className="border-b border-[var(--border)] overflow-x-auto">
        <div className="flex gap-4 min-w-max">
          {[
            ['workflow', 'Workflow Nodes'],
            ['contract', 'Contract View'],
            ['validation', 'Validate'],
            ['versions', 'Versions'],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setActiveTab(key as Tab)}
              className={`px-1 py-3 text-sm font-medium tracking-wide border-b-2 transition-colors ${
                activeTab === key
                  ? 'border-[var(--accent)] text-[var(--text-primary)]'
                  : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--text-muted)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'workflow' && (
        <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
            {nodes.map((node) => (
              <button
                key={node.id}
                onClick={() => setSelectedNodeId(node.id)}
                className={`w-full border-b border-[var(--border)] px-4 py-3 text-left text-sm font-medium last:border-b-0 ${
                  selectedNode?.id === node.id
                    ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                    : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                }`}
              >
                {node.label}
              </button>
            ))}
          </div>
          <div className="min-w-0 bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
            <div className="flex items-center justify-between border-b border-[var(--border)] pb-4 max-md:flex-col max-md:items-start max-md:gap-3">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">{selectedNode?.label}</h3>
              <button
                onClick={saveWorkflow}
                disabled={busy === 'workflow'}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                Save Node
              </button>
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              {selectedNode?.fields.map((field) => (
                <label key={field.path.join('.')} className="block">
                  <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">{field.label}</span>
                  <input
                    type={field.input}
                    value={field.value}
                    onChange={(event) => {
                      setAgentYaml((current) => updateAgentYamlField(current, field.path, event.target.value))
                    }}
                    className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  />
                </label>
              ))}
            </div>
          </div>
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

      {activeTab === 'validation' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
          <div className="flex flex-col gap-3 md:flex-row">
            <input
              value={validationQuestion}
              onChange={(event) => setValidationQuestion(event.target.value)}
              className="flex-1 bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
            <button
              onClick={runValidation}
              disabled={busy === 'validation' || !validationQuestion.trim()}
              className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              Validate
            </button>
          </div>
          <div className="mt-5 divide-y divide-[var(--border)] border border-[var(--border)] rounded-lg overflow-hidden">
            {draft.validation_records.length === 0 ? (
              <EmptyState message="No validation runs yet." />
            ) : (
              draft.validation_records.map((record) => (
                <div key={record.validation_id} className="px-4 py-3 text-sm">
                  <Link to={`/runs/${record.run_id}`} className="font-mono text-xs text-[var(--accent)] hover:underline">{record.run_id}</Link>
                  <span className="ml-3 text-[var(--text-secondary)]">{record.status}</span>
                  <p className="mt-1 text-xs text-[var(--text-muted)] line-clamp-2">{record.summary}</p>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {activeTab === 'versions' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
          <div className="flex items-center justify-between border-b border-[var(--border)] pb-4">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">Published Versions</h3>
              <p className="mt-1 text-xs text-[var(--text-muted)]">{activeVersionId ?? 'No active version'}</p>
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
                    <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)]">Active</span>
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
    </div>
  )
}
