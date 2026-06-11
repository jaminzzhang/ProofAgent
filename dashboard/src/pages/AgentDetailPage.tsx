import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  bindKnowledgeSourceToDraft,
  chatUrl,
  createModelConnection,
  fetchWorkflowTemplate,
  fetchKnowledgeSources,
  fetchModelConnections,
  previewWorkflowNodeContext,
  publishConfigDraft,
  rollbackConfigVersion,
  unbindKnowledgeSourceFromDraft,
  updateConfigDraft,
  updateConfigDraftContract,
  updateWorkflowNodes,
  validateConfigDraft,
} from '../api/client'
import type { SharedModelConnection, KnowledgeSource, WorkflowTemplateDescriptor } from '../api/types'
import { CodeBlock } from '../components/CodeBlock'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { AgentDetailShell } from '../components/agent/AgentDetailShell'
import { AgentMonitor, AgentMonitorSummary } from '../components/agent/AgentMonitor'
import { ModuleEditor } from '../components/agent/ModuleEditor'
import { ModelModuleEditor } from '../components/agent/ModelModuleEditor'
import { KnowledgeModuleEditor } from '../components/agent/KnowledgeModuleEditor'
import { MemoryModuleEditor } from '../components/agent/MemoryModuleEditor'
import { WorkflowModuleEditor } from '../components/agent/WorkflowModuleEditor'
import { ValidateWorkspace } from '../components/agent/ValidateWorkspace'
import { KNOWLEDGE_FIELDS } from '../components/agent/module-configs/knowledge'
import { TOOLS_FIELDS } from '../components/agent/module-configs/tools'
import { POLICY_FIELDS } from '../components/agent/module-configs/policy'
import { MEMORY_FIELDS } from '../components/agent/module-configs/memory'
import { RESPONSE_FIELDS } from '../components/agent/module-configs/response'
import { useConfigDraft } from '../hooks/useConfigDraft'
import { useConfigVersions } from '../hooks/useConfigVersions'
import {
  extractAgentYamlSection,
  readAgentYamlField,
  replaceAgentYamlMapping,
  updateAgentYamlField,
} from '../utils/agentYaml'

type Tab = 'general' | 'workflow' | 'knowledge' | 'tools' | 'policy' | 'model' | 'memory' | 'response' | 'validate' | 'versions' | 'contract' | 'monitor'

export function AgentDetailPage() {
  const { agentId, draftId } = useParams<{ agentId: string; draftId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const { draft, contract, loading, error, refresh } = useConfigDraft(agentId, draftId)
  const {
    versions,
    activeVersionId,
    loading: versionsLoading,
    refresh: refreshVersions,
  } = useConfigVersions(agentId)
  const activeTab = agentDetailTab(searchParams.get('tab'))
  const [displayName, setDisplayName] = useState('')
  const [purpose, setPurpose] = useState('')
  const [agentYaml, setAgentYaml] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [knowledgeSources, setKnowledgeSources] = useState<KnowledgeSource[]>([])
  const [knowledgeSourcesLoaded, setKnowledgeSourcesLoaded] = useState(false)
  const [knowledgeSourceError, setKnowledgeSourceError] = useState<string | null>(null)
  const [modelConnections, setModelConnections] = useState<SharedModelConnection[]>([])
  const [modelConnectionsLoaded, setModelConnectionsLoaded] = useState(false)
  const [workflowDescriptor, setWorkflowDescriptor] = useState<WorkflowTemplateDescriptor | null>(null)
  const [workflowDescriptorError, setWorkflowDescriptorError] = useState<string | null>(null)

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
      })
      .catch((err) => {
        if (!mounted) return
        setKnowledgeSourceError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      mounted = false
    }
  }, [activeTab, knowledgeSourcesLoaded])

  useEffect(() => {
    if (activeTab !== 'model' || modelConnectionsLoaded) return
    let mounted = true
    fetchModelConnections()
      .then((response) => {
        if (!mounted) return
        setModelConnections(response.data)
        setModelConnectionsLoaded(true)
      })
      .catch(() => {
        if (!mounted) return
        setModelConnections([])
        setModelConnectionsLoaded(true)
      })
    return () => {
      mounted = false
    }
  }, [activeTab, modelConnectionsLoaded])

  const workflowTemplateName = useMemo(
    () => readAgentYamlField(agentYaml, ['workflow', 'template']),
    [agentYaml],
  )

  useEffect(() => {
    if (activeTab !== 'workflow') return
    if (!workflowTemplateName) {
      setWorkflowDescriptor(null)
      setWorkflowDescriptorError('workflow.template is not configured.')
      return
    }

    let mounted = true
    fetchWorkflowTemplate(workflowTemplateName)
      .then((descriptor) => {
        if (!mounted) return
        setWorkflowDescriptor(descriptor)
        setWorkflowDescriptorError(null)
      })
      .catch((err) => {
        if (!mounted) return
        setWorkflowDescriptor(null)
        setWorkflowDescriptorError(err instanceof Error ? err.message : String(err))
      })

    return () => {
      mounted = false
    }
  }, [activeTab, workflowTemplateName])

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
      })
      setStatus('Workflow node configuration saved.')
      refresh()
    })
  }

  async function saveWorkflowNodes(payload: Parameters<typeof updateWorkflowNodes>[2]) {
    if (!agentId || !draftId) return
    await runAction('workflow-nodes', async () => {
      const updated = await updateWorkflowNodes(agentId, draftId, payload)
      setAgentYaml(updated.agent_yaml)
      setStatus('Workflow node configuration saved.')
      refresh()
    })
  }

  async function previewWorkflowNode(
    nodeId: string,
    payload: Parameters<typeof previewWorkflowNodeContext>[3],
  ) {
    if (!agentId || !draftId) throw new Error('Draft route is missing.')
    return previewWorkflowNodeContext(agentId, draftId, nodeId, payload)
  }

  async function bindKnowledgeSource(payload: Parameters<typeof bindKnowledgeSourceToDraft>[2]) {
    if (!agentId || !draftId || !payload.source_id) return
    await runAction('knowledge-binding', async () => {
      const updated = await bindKnowledgeSourceToDraft(agentId, draftId, payload)
      setAgentYaml(updated.agent_yaml)
      setStatus('Knowledge source binding saved.')
      refresh()
    })
  }

  async function unbindKnowledgeSource(bindingId: string) {
    if (!agentId || !draftId || !bindingId) return
    await runAction('knowledge-binding', async () => {
      const updated = await unbindKnowledgeSourceFromDraft(agentId, draftId, bindingId)
      setAgentYaml(updated.agent_yaml)
      setStatus('Knowledge source binding removed.')
      refresh()
    })
  }

  async function publishDraft() {
    if (!agentId || !draftId || !latestValidation) return
    await runAction('publish', async () => {
      const version = await publishConfigDraft(agentId, draftId, {
        validation_run_id: latestValidation.run_id,
      })
      setStatus(`Published ${version.version_id}.`)
      refreshVersions()
    })
  }

  async function rollback(versionId: string) {
    if (!agentId) return
    await runAction(`rollback-${versionId}`, async () => {
      await rollbackConfigVersion(agentId, versionId)
      setStatus(`Active version set to ${versionId}.`)
      refreshVersions()
    })
  }

  const CONFIGURE_MODULES = [
    { id: 'general', label: 'Overview' },
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

  function setActiveTab(moduleId: string) {
    const nextTab = agentDetailTab(moduleId)
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      if (nextTab === 'general') {
        next.delete('tab')
      } else {
        next.set('tab', nextTab)
      }
      return next
    })
  }

  return (
    <AgentDetailShell
      agentName={displayName}
      modules={CONFIGURE_MODULES}
      lifecycle={LIFECYCLE_TABS}
      activeModule={activeTab}
      onModuleChange={setActiveTab}
    >
      {activeTab === 'general' && (
        <div className="space-y-5">
          <section className="border border-[var(--border)] bg-[var(--bg-surface)] p-6">
            <div className="flex flex-col gap-4 border-b border-[var(--border)] pb-4 md:flex-row md:items-start md:justify-between">
              <div>
                <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
                  Agent Overview
                </h3>
                <p className="mt-1 text-sm text-[var(--text-muted)]">
                  Identity, draft status, and recent operating signals for this Agent.
                </p>
              </div>
              <button
                onClick={saveBasics}
                disabled={busy === 'basics'}
                className="w-fit rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                {busy === 'basics' ? 'Saving...' : 'Save'}
              </button>
            </div>

            <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
              <div className="space-y-4">
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Display Name
                  </label>
                  <input
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Purpose
                  </label>
                  <textarea
                    value={purpose}
                    onChange={(event) => setPurpose(event.target.value)}
                    rows={4}
                    className="w-full resize-none rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>
              </div>

              <dl className="grid content-start gap-3 text-sm">
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Agent ID</dt>
                  <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">{draft.agent_id}</dd>
                </div>
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Draft ID</dt>
                  <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">{draft.draft_id}</dd>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                    <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Validations</dt>
                    <dd className="mt-1 text-lg font-semibold text-[var(--text-primary)]">{draft.validation_records.length}</dd>
                  </div>
                  <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                    <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Versions</dt>
                    <dd className="mt-1 text-lg font-semibold text-[var(--text-primary)]">{versions.length}</dd>
                  </div>
                </div>
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Active Version</dt>
                  <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">{activeVersionId ?? 'Not published'}</dd>
                </div>
              </dl>
            </div>
          </section>

          {agentId && <AgentMonitorSummary agentId={agentId} />}
        </div>
      )}

      {activeTab === 'workflow' && (
        <WorkflowModuleEditor
          agentYaml={agentYaml}
          descriptor={workflowDescriptor}
          descriptorError={workflowDescriptorError}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onSaveCore={saveWorkflow}
          onSaveNodes={saveWorkflowNodes}
          onPreviewNode={previewWorkflowNode}
          busy={busy === 'workflow'}
          nodeBusy={busy === 'workflow-nodes'}
        />
      )}

      {activeTab === 'knowledge' && (
        <KnowledgeModuleEditor
          agentYaml={agentYaml}
          knowledgeSources={knowledgeSources}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onBindSource={bindKnowledgeSource}
          onUnbindSource={unbindKnowledgeSource}
          onSave={saveWorkflow}
          busy={busy === 'workflow' || busy === 'knowledge-binding'}
          knowledgeSourceError={knowledgeSourceError}
        />
      )}

      {activeTab === 'tools' && (
        <ModuleEditor
          title="Tools Configuration"
          description="Tool contracts file reference"
          fields={TOOLS_FIELDS}
          yamlSection="tools"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
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
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onSave={saveWorkflow}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'model' && (
        <ModelModuleEditor
          agentYaml={agentYaml}
          modelConnections={modelConnections}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onModelConfigChange={(path, value) => setAgentYaml((current: string) => replaceAgentYamlMapping(current, path, value))}
          onCreateSharedModelConnection={async (payload) => {
            const connection = await createModelConnection(payload)
            setModelConnections((current) => [...current, connection])
            return connection
          }}
          onSave={saveWorkflow}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'memory' && (
        <MemoryModuleEditor
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
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
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
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

function agentDetailTab(value: string | null): Tab {
  const tabs: Tab[] = [
    'general',
    'workflow',
    'knowledge',
    'tools',
    'policy',
    'model',
    'memory',
    'response',
    'validate',
    'versions',
    'contract',
    'monitor',
  ]
  return value && tabs.includes(value as Tab) ? (value as Tab) : 'general'
}
