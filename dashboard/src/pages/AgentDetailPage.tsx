import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  bindKnowledgeSourceToDraft,
  chatUrl,
  fetchKnowledgeSources,
  publishConfigDraft,
  rollbackConfigVersion,
  updateConfigDraft,
  updateConfigDraftContract,
  validateConfigDraft,
} from '../api/client'
import type { KnowledgeSource } from '../api/types'
import { CodeBlock } from '../components/CodeBlock'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { AgentDetailShell } from '../components/agent/AgentDetailShell'
import { AgentMonitor } from '../components/agent/AgentMonitor'
import { ModuleEditor } from '../components/agent/ModuleEditor'
import { WorkflowAccordion } from '../components/agent/WorkflowAccordion'
import { ValidateWorkspace } from '../components/agent/ValidateWorkspace'
import { WORKFLOW_FIELDS } from '../components/agent/module-configs/workflow'
import { KNOWLEDGE_FIELDS } from '../components/agent/module-configs/knowledge'
import { TOOLS_FIELDS } from '../components/agent/module-configs/tools'
import { POLICY_FIELDS } from '../components/agent/module-configs/policy'
import { MODEL_FIELDS } from '../components/agent/module-configs/model'
import { MEMORY_FIELDS } from '../components/agent/module-configs/memory'
import { RESPONSE_FIELDS } from '../components/agent/module-configs/response'
import { useConfigDraft } from '../hooks/useConfigDraft'
import { useConfigVersions } from '../hooks/useConfigVersions'
import { buildWorkflowNodes, extractAgentYamlSection, updateAgentYamlField } from '../utils/agentYaml'

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
  const [status, setStatus] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [knowledgeSources, setKnowledgeSources] = useState<KnowledgeSource[]>([])
  const [knowledgeSourcesLoaded, setKnowledgeSourcesLoaded] = useState(false)
  const [knowledgeSourceError, setKnowledgeSourceError] = useState<string | null>(null)
  const [selectedKnowledgeSourceId, setSelectedKnowledgeSourceId] = useState('')
  const [bindingAlias, setBindingAlias] = useState('')
  const [bindingFailureMode, setBindingFailureMode] = useState<'required' | 'advisory'>('required')
  const [bindingFusionWeight, setBindingFusionWeight] = useState('1')
  const [bindingTopK, setBindingTopK] = useState('')

  useEffect(() => {
    if (draft) {
      setDisplayName(draft.display_name)
      setPurpose(draft.purpose)
    }
  }, [draft])

  useEffect(() => {
    if (contract) setAgentYaml(contract.agent_yaml)
  }, [contract])

  useEffect(() => {
    if (activeTab !== 'knowledge' || knowledgeSourcesLoaded) return
    let mounted = true
    fetchKnowledgeSources()
      .then((response) => {
        if (!mounted) return
        setKnowledgeSources(response.data)
        setKnowledgeSourcesLoaded(true)
        setKnowledgeSourceError(null)
        setSelectedKnowledgeSourceId((current) =>
          response.data.some((source) => source.source_id === current)
            ? current
            : response.data[0]?.source_id ?? '',
        )
      })
      .catch((err) => {
        if (!mounted) return
        setKnowledgeSourceError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      mounted = false
    }
  }, [activeTab, knowledgeSourcesLoaded])

  const nodes = useMemo(() => buildWorkflowNodes(agentYaml), [agentYaml])
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? nodes[0]
  const latestValidation = draft?.validation_records[draft.validation_records.length - 1]
  const isCustomerFacing = Boolean(extractAgentYamlSection(agentYaml, 'customer'))

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

  async function bindKnowledgeSource() {
    const sourceId = selectedKnowledgeSourceId || knowledgeSources[0]?.source_id
    if (!agentId || !draftId || !sourceId) return
    await runAction('knowledge-binding', async () => {
      const payload: {
        source_id: string
        alias: string
        failure_mode: 'required' | 'advisory'
        fusion_weight: number
        top_k?: number
        actor: string
      } = {
        source_id: sourceId,
        alias: bindingAlias,
        failure_mode: bindingFailureMode,
        fusion_weight: Number(bindingFusionWeight) || 1,
        actor: 'dashboard',
      }
      const topK = Number(bindingTopK)
      if (bindingTopK.trim() && Number.isFinite(topK) && topK > 0) {
        payload.top_k = topK
      }
      const updated = await bindKnowledgeSourceToDraft(agentId, draftId, payload)
      setAgentYaml(updated.agent_yaml)
      setStatus('Knowledge source binding saved.')
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

      {activeTab === 'knowledge' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
                  Bind Shared Source
                </h3>
                <p className="mt-1 text-sm text-[var(--text-muted)]">
                  Select a shared Knowledge Source from /knowledge and attach it to this Agent draft. Provider runtime and documents stay source-owned.
                </p>
              </div>
              <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)]">
                {knowledgeSources.length} sources
              </span>
            </div>
            {knowledgeSourceError && (
              <div className="mt-4 rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
                {knowledgeSourceError}
              </div>
            )}
            {knowledgeSources.length === 0 ? (
              <div className="mt-4">
                <EmptyState message="No shared Knowledge Sources yet. Create one in /knowledge, then bind it here." />
              </div>
            ) : (
              <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,0.7fr)]">
                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                      Knowledge Source
                    </label>
                    <select
                      value={selectedKnowledgeSourceId}
                      onChange={(event) => setSelectedKnowledgeSourceId(event.target.value)}
                      className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                    >
                      {knowledgeSources.map((source) => (
                        <option key={source.source_id} value={source.source_id}>
                          {source.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                        Alias
                      </label>
                      <input
                        value={bindingAlias}
                        onChange={(event) => setBindingAlias(event.target.value)}
                        placeholder="optional display alias"
                        className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                        Failure Mode
                      </label>
                      <select
                        value={bindingFailureMode}
                        onChange={(event) =>
                          setBindingFailureMode(event.target.value as 'required' | 'advisory')
                        }
                        className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      >
                        <option value="required">required</option>
                        <option value="advisory">advisory</option>
                      </select>
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                        Fusion Weight
                      </label>
                      <input
                        type="number"
                        min="0.1"
                        step="0.1"
                        value={bindingFusionWeight}
                        onChange={(event) => setBindingFusionWeight(event.target.value)}
                        className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                        Top K Override
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={bindingTopK}
                        onChange={(event) => setBindingTopK(event.target.value)}
                        placeholder="use Agent retrieval default"
                        className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      />
                    </div>
                  </div>
                  <button
                    onClick={bindKnowledgeSource}
                    disabled={busy === 'knowledge-binding' || !selectedKnowledgeSourceId}
                    className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                  >
                    {busy === 'knowledge-binding' ? 'Binding...' : 'Bind Source'}
                  </button>
                </div>
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4">
                  <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Available Sources
                  </div>
                  <div className="mt-3 space-y-3">
                    {knowledgeSources.map((source) => (
                      <div key={source.source_id} className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-3">
                        <div className="text-sm font-medium text-[var(--text-primary)]">
                          Name: {source.name}
                        </div>
                        <div className="mt-1 font-mono text-xs text-[var(--text-muted)]">{source.source_id}</div>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--text-muted)]">
                          <span>{source.provider}</span>
                          <span>{source.ready_document_count}/{source.document_count} ready</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              Knowledge Bindings
            </h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              Agents bind shared Knowledge Sources by source_id. Provider settings are managed in /knowledge, not on the Agent.
            </p>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Sources
                </div>
                <CodeBlock>{extractAgentYamlSection(agentYaml, 'knowledge_sources') || 'knowledge_sources: []'}</CodeBlock>
              </div>
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Bindings
                </div>
                <CodeBlock>{extractAgentYamlSection(agentYaml, 'knowledge_bindings') || 'knowledge_bindings: []'}</CodeBlock>
              </div>
            </div>
          </div>
          <ModuleEditor
            title="Retrieval Configuration"
            description="Agent-level retrieval controls apply across bound knowledge sources"
            fields={KNOWLEDGE_FIELDS}
            yamlSection="retrieval"
            agentYaml={agentYaml}
            onFieldChange={(path, value) => setAgentYaml((current) => updateAgentYamlField(current, path, value))}
            onSave={saveWorkflow}
            busy={busy === 'workflow'}
          />
        </div>
      )}

      {activeTab === 'tools' && (
        <ModuleEditor
          title="Tools Configuration"
          description="Tool contracts file reference"
          fields={TOOLS_FIELDS}
          yamlSection="tools"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current) => updateAgentYamlField(current, path, value))}
          onSave={saveWorkflow}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'policy' && (
        <ModuleEditor
          title="Policy Configuration"
          description="Policy rules file reference"
          fields={POLICY_FIELDS}
          yamlSection="policy"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current) => updateAgentYamlField(current, path, value))}
          onSave={saveWorkflow}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'model' && (
        <ModuleEditor
          title="Model Configuration"
          description="Model providers for answer, planner, and reviewer roles"
          fields={MODEL_FIELDS}
          yamlSection="model"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current) => updateAgentYamlField(current, path, value))}
          onSave={saveWorkflow}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'memory' && (
        <ModuleEditor
          title="Memory Configuration"
          description="Memory provider and scope settings"
          fields={MEMORY_FIELDS}
          yamlSection="memory"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current) => updateAgentYamlField(current, path, value))}
          onSave={saveWorkflow}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'response' && (
        <ModuleEditor
          title="Response Configuration"
          description="Response disclosure and detail settings"
          fields={RESPONSE_FIELDS}
          yamlSection="response"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current) => updateAgentYamlField(current, path, value))}
          onSave={saveWorkflow}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'validate' && agentId && draftId && (
        <ValidateWorkspace
          agentId={agentId}
          draftId={draftId}
          validationRecords={draft.validation_records}
          onValidate={(question) =>
            runAction('validation', async () => {
              const result = await validateConfigDraft(agentId, draftId, {
                question,
                actor: 'dashboard',
              })
              setStatus(`Validation run ${result.run_id} completed with ${result.outcome}.`)
              refresh()
            })
          }
          busy={busy === 'validation'}
        />
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
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <a
                        href={chatUrl(`/operator/agents/${version.agent_id}/new`)}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                      >
                        Open in Operator Chat
                      </a>
                      {isCustomerFacing && (
                        <a
                          href={chatUrl(`/customer/agents/${version.agent_id}`)}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                        >
                          Open in Customer Chat
                        </a>
                      )}
                      <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)]">
                        Active
                      </span>
                    </div>
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

      {activeTab === 'monitor' && agentId && (
        <AgentMonitor agentId={agentId} />
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
