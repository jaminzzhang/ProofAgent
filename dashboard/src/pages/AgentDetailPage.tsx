import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  bindKnowledgeSourceToDraft,
  chatUrl,
  createModelConnection,
  createConfigDraftSkillPack,
  deleteConfigDraftSkillPack,
  fetchConfigDraftSkills,
  fetchWorkflowTemplate,
  fetchKnowledgeSources,
  fetchModelConnections,
  previewWorkflowStageContext,
  publishConfigDraft,
  rollbackConfigVersion,
  unbindKnowledgeSourceFromDraft,
  updateConfigDraft,
  updateConfigDraftSkillPack,
  updateConfigDraftContract,
  updateWorkflowStages,
  validateConfigDraft,
} from '../api/client'
import type {
  BusinessFlowSkillPackConfiguration,
  BusinessFlowSkillPackCreateRequest,
  BusinessFlowSkillPackUpdateRequest,
  SharedModelConnection,
  KnowledgeSource,
  WorkflowTemplateDescriptor,
} from '../api/types'
import { CodeBlock } from '../components/CodeBlock'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { Badge, Button, ConfigPanel } from '@proofagent/ui'
import { AgentDetailShell } from '../components/agent/AgentDetailShell'
import { AgentMonitor, AgentMonitorSummary } from '../components/agent/AgentMonitor'
import { ModuleEditor } from '../components/agent/ModuleEditor'
import { ModelModuleEditor } from '../components/agent/ModelModuleEditor'
import { KnowledgeModuleEditor } from '../components/agent/KnowledgeModuleEditor'
import { MemoryModuleEditor } from '../components/agent/MemoryModuleEditor'
import { SkillsModuleEditor } from '../components/agent/SkillsModuleEditor'
import { WorkflowModuleEditor } from '../components/agent/WorkflowModuleEditor'
import { ValidateWorkspace } from '../components/agent/ValidateWorkspace'
import { RunDetailDrawer } from '../components/agent/RunDetailDrawer'
import { KNOWLEDGE_FIELDS } from '../components/agent/module-configs/knowledge'
import { TOOLS_FIELDS } from '../components/agent/module-configs/tools'
import { POLICY_FIELDS } from '../components/agent/module-configs/policy'
import { RESPONSE_FIELDS } from '../components/agent/module-configs/response'
import { useConfigDraft } from '../hooks/useConfigDraft'
import { useConfigVersions } from '../hooks/useConfigVersions'
import { useLocale } from '../i18n/locale'
import {
  readAgentYamlField,
  replaceAgentContextConfiguration,
  replaceAgentYamlMapping,
  replaceMemoryCapabilityConfiguration,
  updateAgentYamlField,
} from '../utils/agentYaml'

type Tab = 'general' | 'workflow' | 'skills' | 'knowledge' | 'tools' | 'policy' | 'model' | 'memory' | 'response' | 'validate' | 'versions' | 'contract' | 'monitor'

export function AgentDetailPage() {
  const { t } = useLocale()
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
  const [skillsConfig, setSkillsConfig] = useState<BusinessFlowSkillPackConfiguration | null>(null)
  const [skillsLoaded, setSkillsLoaded] = useState(false)
  const [skillsError, setSkillsError] = useState<string | null>(null)
  const [selectedRunDetailId, setSelectedRunDetailId] = useState<string | null>(null)

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
      setWorkflowDescriptorError(t('agentDetail.workflowTemplateMissing'))
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
  }, [activeTab, workflowTemplateName, t])

  useEffect(() => {
    if (activeTab !== 'skills' || skillsLoaded || !agentId || !draftId) return
    let mounted = true
    fetchConfigDraftSkills(agentId, draftId)
      .then((response) => {
        if (!mounted) return
        setSkillsConfig(response)
        setSkillsLoaded(true)
        setSkillsError(null)
      })
      .catch((err) => {
        if (!mounted) return
        setSkillsError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      mounted = false
    }
  }, [activeTab, agentId, draftId, skillsLoaded])

  const latestValidation = draft?.validation_records[draft.validation_records.length - 1]
  const memoryReadinessBlockers = useMemo(
    () => memoryConfigurationBlockers(agentYaml, t),
    [agentYaml, t],
  )

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
      setStatus(t('agentDetail.draftFieldsSaved'))
      refresh()
    })
  }

  async function saveAgentYaml(successMessage = t('agentDetail.configurationSaved')) {
    if (!agentId || !draftId) return
    await runAction('workflow', async () => {
      await updateConfigDraftContract(agentId, draftId, {
        agent_yaml: agentYaml,
      })
      setStatus(successMessage)
      refresh()
    })
  }

  async function saveWorkflowStages(payload: Parameters<typeof updateWorkflowStages>[2]) {
    if (!agentId || !draftId) return
    await runAction('workflow-stages', async () => {
      // Persist the core contract first so the server-side workflow.template
      // matches the template_descriptor_version sent with the stages. Without
      // this, switching the Template dropdown and saving stages sends a
      // descriptor_version for a template the server has not stored yet, which
      // the backend rejects with a 400 "template_descriptor_version does not
      // match registered template descriptor".
      await updateConfigDraftContract(agentId, draftId, {
        agent_yaml: agentYaml,
      })
      const updated = await updateWorkflowStages(agentId, draftId, payload)
      setAgentYaml(updated.agent_yaml)
      setStatus(t('agentDetail.workflowStagesSaved'))
      refresh()
    })
  }

  async function previewWorkflowStage(
    stageId: string,
    payload: Parameters<typeof previewWorkflowStageContext>[3],
  ) {
    if (!agentId || !draftId) throw new Error(t('agentDetail.draftRouteMissing'))
    return previewWorkflowStageContext(agentId, draftId, stageId, payload)
  }

  async function createSkillPack(payload: BusinessFlowSkillPackCreateRequest) {
    if (!agentId || !draftId) return
    await runAction('skills', async () => {
      const updated = await createConfigDraftSkillPack(agentId, draftId, payload)
      setSkillsConfig(updated)
      setSkillsLoaded(true)
      setSkillsError(null)
      setStatus(t('agentDetail.skillPackCreated'))
      refresh()
    })
  }

  async function updateSkillPack(packId: string, payload: BusinessFlowSkillPackUpdateRequest) {
    if (!agentId || !draftId) return
    await runAction('skills', async () => {
      const updated = await updateConfigDraftSkillPack(agentId, draftId, packId, payload)
      setSkillsConfig(updated)
      setSkillsLoaded(true)
      setSkillsError(null)
      setStatus(t('agentDetail.skillPackSaved'))
      refresh()
    })
  }

  async function deleteSkillPack(packId: string) {
    if (!agentId || !draftId) return
    await runAction('skills', async () => {
      const updated = await deleteConfigDraftSkillPack(agentId, draftId, packId)
      setSkillsConfig(updated)
      setSkillsLoaded(true)
      setSkillsError(null)
      setStatus(t('agentDetail.skillPackDeleted'))
      refresh()
    })
  }

  async function bindKnowledgeSource(payload: Parameters<typeof bindKnowledgeSourceToDraft>[2]) {
    if (!agentId || !draftId || !payload.source_id) return
    await runAction('knowledge-binding', async () => {
      const updated = await bindKnowledgeSourceToDraft(agentId, draftId, payload)
      setAgentYaml(updated.agent_yaml)
      setStatus(t('agentDetail.knowledgeBindingSaved'))
      refresh()
    })
  }

  async function unbindKnowledgeSource(bindingId: string) {
    if (!agentId || !draftId || !bindingId) return
    await runAction('knowledge-binding', async () => {
      const updated = await unbindKnowledgeSourceFromDraft(agentId, draftId, bindingId)
      setAgentYaml(updated.agent_yaml)
      setStatus(t('agentDetail.knowledgeBindingRemoved'))
      refresh()
    })
  }

  async function publishDraft() {
    if (!agentId || !draftId || !latestValidation || memoryReadinessBlockers.length > 0) return
    await runAction('publish', async () => {
      const version = await publishConfigDraft(agentId, draftId, {
        validation_run_id: latestValidation.run_id,
      })
      setStatus(t('agentDetail.publishedVersion').replace('{version}', version.version_id))
      refreshVersions()
    })
  }

  function updateConfigurationYamlField(current: string, path: string[], value: string): string {
    if (path[0] === 'context') {
      return replaceAgentContextConfiguration(current, path, value)
    }
    if (path[0] === 'capabilities' && path[1] === 'memory') {
      return replaceMemoryCapabilityConfiguration(current, path, value)
    }
    return updateAgentYamlField(current, path, value)
  }

  async function rollback(versionId: string) {
    if (!agentId) return
    await runAction(`rollback-${versionId}`, async () => {
      await rollbackConfigVersion(agentId, versionId)
      setStatus(t('agentDetail.activeVersionSet').replace('{version}', versionId))
      refreshVersions()
    })
  }

  const CONFIGURE_MODULES = [
    { id: 'general', label: t('agentDetail.tabOverview') },
    { id: 'workflow', label: t('agentDetail.tabWorkflow') },
    { id: 'skills', label: t('agentDetail.tabSkills') },
    { id: 'knowledge', label: t('agentDetail.tabKnowledge') },
    { id: 'tools', label: t('agentDetail.tabTools') },
    { id: 'policy', label: t('agentDetail.tabPolicy') },
    { id: 'model', label: t('agentDetail.tabModel') },
    { id: 'memory', label: t('agentDetail.tabMemory') },
    { id: 'response', label: t('agentDetail.tabResponse') },
  ]

  const LIFECYCLE_TABS = [
    { id: 'validate', label: t('agentDetail.tabValidate') },
    { id: 'versions', label: t('agentDetail.tabVersions') },
    { id: 'contract', label: t('agentDetail.tabContract') },
    { id: 'monitor', label: t('agentDetail.tabMonitor') },
  ]

  if (loading) return <div className="py-12 flex justify-center"><LoadingSpinner /></div>
  if (error) return <div className="text-[var(--danger)] text-sm">{error}</div>
  if (!draft || !contract) return <div className="text-[var(--text-muted)] text-sm">{t('agentDetail.draftNotFound')}</div>

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
                  {t('agentDetail.overviewTitle')}
                </h3>
                <p className="mt-1 text-sm text-[var(--text-muted)]">
                  {t('agentDetail.overviewDescription')}
                </p>
              </div>
              <button
                onClick={saveBasics}
                disabled={busy === 'basics'}
                className="w-fit rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                {busy === 'basics' ? t('agentDetail.saving') : t('agentDetail.save')}
              </button>
            </div>

            <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
              <div className="space-y-4">
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    <span>{t('agentDetail.displayName')}</span>
                  </label>
                  <input
                    aria-label={t('agentDetail.displayName')}
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    <span>{t('common.purpose')}</span>
                  </label>
                  <textarea
                    aria-label={t('common.purpose')}
                    value={purpose}
                    onChange={(event) => setPurpose(event.target.value)}
                    rows={4}
                    className="w-full resize-none rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>
              </div>

              <dl className="grid content-start gap-3 text-sm">
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('agentDetail.agentId')}</dt>
                  <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">{draft.agent_id}</dd>
                </div>
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('agentDetail.draftId')}</dt>
                  <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">{draft.draft_id}</dd>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                    <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('agentDetail.validations')}</dt>
                    <dd className="mt-1 text-lg font-semibold text-[var(--text-primary)]">{draft.validation_records.length}</dd>
                  </div>
                  <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                    <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('agentDetail.versions')}</dt>
                    <dd className="mt-1 text-lg font-semibold text-[var(--text-primary)]">{versions.length}</dd>
                  </div>
                </div>
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('agentDetail.activeVersion')}</dt>
                  <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">{activeVersionId ?? t('agentDetail.notPublished')}</dd>
                </div>
              </dl>
            </div>
          </section>

          {agentId && (
            <AgentMonitorSummary
              agentId={agentId}
              onOpenRunDetail={setSelectedRunDetailId}
            />
          )}
        </div>
      )}

      {activeTab === 'workflow' && (
        <WorkflowModuleEditor
          agentYaml={agentYaml}
          descriptor={workflowDescriptor}
          descriptorError={workflowDescriptorError}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onSaveCore={() => saveAgentYaml(t('agentDetail.workflowSaved'))}
          onSaveStages={saveWorkflowStages}
          onPreviewStage={previewWorkflowStage}
          busy={busy === 'workflow'}
          stageBusy={busy === 'workflow-stages'}
        />
      )}

      {activeTab === 'skills' && (
        <SkillsModuleEditor
          config={skillsConfig}
          loading={!skillsLoaded && !skillsError}
          error={skillsError}
          busy={busy === 'skills'}
          onCreatePack={createSkillPack}
          onUpdatePack={updateSkillPack}
          onDeletePack={deleteSkillPack}
        />
      )}

      {activeTab === 'knowledge' && (
        <KnowledgeModuleEditor
          agentYaml={agentYaml}
          knowledgeSources={knowledgeSources}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onBindSource={bindKnowledgeSource}
          onUnbindSource={unbindKnowledgeSource}
          onSave={() => saveAgentYaml(t('agentDetail.knowledgeSaved'))}
          busy={busy === 'workflow' || busy === 'knowledge-binding'}
          knowledgeSourceError={knowledgeSourceError}
        />
      )}

      {activeTab === 'tools' && (
        <ModuleEditor
          title={t('agentDetail.toolsTitle')}
          description={t('agentDetail.toolsDescription')}
          fields={TOOLS_FIELDS}
          yamlSection="tools"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onSave={() => saveAgentYaml(t('agentDetail.toolsSaved'))}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'policy' && (
        <ModuleEditor
          title={t('agentDetail.policyTitle')}
          description={t('agentDetail.policyDescription')}
          fields={POLICY_FIELDS}
          yamlSection="policy"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onSave={() => saveAgentYaml(t('agentDetail.policySaved'))}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'model' && (
        <ModelModuleEditor
          agentYaml={agentYaml}
          modelConnections={modelConnections}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateConfigurationYamlField(current, path, value))}
          onModelConfigChange={(path, value) => setAgentYaml((current: string) => replaceAgentYamlMapping(current, path, value))}
          onCreateSharedModelConnection={async (payload) => {
            const connection = await createModelConnection(payload)
            setModelConnections((current) => [...current, connection])
            return connection
          }}
          onSave={() => saveAgentYaml(t('agentDetail.modelSaved'))}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'memory' && (
        <MemoryModuleEditor
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateConfigurationYamlField(current, path, value))}
          onSave={() => saveAgentYaml(t('agentDetail.memorySaved'))}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'response' && (
        <ModuleEditor
          title={t('agentDetail.responseTitle')}
          description={t('agentDetail.responseDescription')}
          fields={RESPONSE_FIELDS}
          yamlSection="response"
          agentYaml={agentYaml}
          onFieldChange={(path, value) => setAgentYaml((current: string) => updateAgentYamlField(current, path, value))}
          onSave={() => saveAgentYaml(t('agentDetail.responseSaved'))}
          busy={busy === 'workflow'}
        />
      )}

      {activeTab === 'validate' && agentId && draftId && (
        <ValidateWorkspace
          agentId={agentId}
          draftId={draftId}
          validationRecords={draft.validation_records}
          onOpenRunDetail={setSelectedRunDetailId}
          onValidate={(question, options) =>
            runAction('validation', async () => {
              const result = await validateConfigDraft(agentId, draftId, {
                question,
                ...options,
              })
              setStatus(
                t('agentDetail.validationCompleted')
                  .replace('{runId}', result.run_id)
                  .replace('{outcome}', result.outcome),
              )
              refresh()
            })
          }
          busy={busy === 'validation'}
          readinessBlockers={memoryReadinessBlockers}
        />
      )}

      {activeTab === 'versions' && (
        <ConfigPanel
          headingLevel={3}
          title={t('agentDetail.publishedVersions')}
          description={activeVersionId ?? t('agentDetail.noActiveVersion')}
          actions={
            <Button
              variant="outline"
              size="sm"
              onClick={publishDraft}
              disabled={busy === 'publish' || !latestValidation || memoryReadinessBlockers.length > 0}
            >
              {t('agentDetail.publish')}
            </Button>
          }
        >
          {memoryReadinessBlockers.length > 0 && (
            <BlockingReasons title={t('validate.readinessBlocked')} reasons={memoryReadinessBlockers} />
          )}
          {versionsLoading ? (
            <div className="flex justify-center py-8"><LoadingSpinner size="sm" /></div>
          ) : versions.length === 0 ? (
            <EmptyState message={t('agentDetail.noPublishedVersions')} />
          ) : (
            <div className="mt-1 divide-y divide-[var(--border)]">
              {versions.map((version) => {
                const isActive = version.version_id === activeVersionId
                return (
                  <div
                    key={version.version_id}
                    className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div
                        translate="no"
                        className="break-all font-mono text-xs text-[var(--text-primary)]"
                      >
                        {version.version_id}
                      </div>
                      <div
                        translate="no"
                        className="mt-1 break-all text-xs text-[var(--text-muted)]"
                      >
                        {t('agentDetail.validatedBy').replace(
                          '{runId}',
                          version.validation_run_id,
                        )}
                      </div>
                    </div>
                    {isActive ? (
                      <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                        <a
                          href={chatUrl(`/operator/agents/${version.agent_id}/new`)}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                        >
                          {t('agentDetail.openOperator')}
                        </a>
                        <Badge variant="success">{t('agentDetail.active')}</Badge>
                      </div>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => rollback(version.version_id)}
                        disabled={busy === `rollback-${version.version_id}`}
                        className="shrink-0"
                      >
                        {t('agentDetail.rollback')}
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </ConfigPanel>
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
        <AgentMonitor agentId={agentId} onOpenRunDetail={setSelectedRunDetailId} />
      )}

      <RunDetailDrawer
        runId={selectedRunDetailId}
        open={selectedRunDetailId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedRunDetailId(null)
        }}
      />

      {(status || actionError) && (
        <div
          role={actionError ? 'alert' : 'status'}
          aria-live={actionError ? 'assertive' : 'polite'}
          className={`fixed bottom-4 right-4 max-w-sm rounded-md border px-4 py-3 text-sm shadow-lg ${
            actionError
              ? 'border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger-fg)]'
              : 'border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)]'
          }`}
        >
          {actionError ?? status}
        </div>
      )}
    </AgentDetailShell>
  )
}

function BlockingReasons({ title, reasons }: { title: string; reasons: string[] }) {
  return (
    <div className="mb-4 rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] p-3 text-sm text-[var(--danger-fg)]">
      <div className="font-semibold">{title}</div>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </div>
  )
}

function memoryConfigurationBlockers(
  agentYaml: string,
  t: (key: string, fallback?: string) => string,
): string[] {
  const blockers: string[] = []
  const memoryEnabledValue = readAgentYamlField(agentYaml, ['capabilities', 'memory', 'enabled'])
  const memoryProvider = readAgentYamlField(agentYaml, ['capabilities', 'memory', 'provider'])
  const canonicalMemoryFields = [
    memoryEnabledValue,
    memoryProvider,
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'case', 'enabled']),
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'case', 'retention_days']),
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'case', 'max_records']),
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'case', 'allow_restricted']),
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'user', 'enabled']),
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'user', 'retention_days']),
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'user', 'max_records']),
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'user', 'allow_restricted']),
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'shared', 'enabled']),
  ]
  const contextRecallFields = [
    readAgentYamlField(agentYaml, ['context', 'source_policies', 'memory_recall', 'scopes', 'case', 'enabled']),
    readAgentYamlField(agentYaml, ['context', 'source_policies', 'memory_recall', 'scopes', 'user', 'enabled']),
    readAgentYamlField(agentYaml, ['context', 'source_policies', 'memory_recall', 'scopes', 'shared', 'enabled']),
  ]
  const hasMemoryConfiguration =
    canonicalMemoryFields.some(Boolean) || contextRecallFields.some(Boolean)
  if (!hasMemoryConfiguration) return blockers

  const memoryEnabled = memoryEnabledValue === 'true'

  if (memoryEnabled && !memoryProvider) {
    blockers.push(t('memory.blockProviderRequired'))
  }

  const caseMemoryEnabled =
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'case', 'enabled']) === 'true'
  const userMemoryEnabled =
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'user', 'enabled']) === 'true'
  if (
    memoryEnabled &&
    (memoryProvider === 'local' || memoryProvider === 'mem0') &&
    !caseMemoryEnabled &&
    !userMemoryEnabled
  ) {
    blockers.push(t('memory.blockScopeRequired'))
  }

  const sharedMemoryEnabled =
    readAgentYamlField(agentYaml, ['capabilities', 'memory', 'scopes', 'shared', 'enabled']) === 'true' ||
    readAgentYamlField(agentYaml, ['context', 'source_policies', 'memory_recall', 'scopes', 'shared', 'enabled']) === 'true'
  if (sharedMemoryEnabled) {
    blockers.push(t('memory.blockShared'))
  }

  return blockers
}

function agentDetailTab(value: string | null): Tab {
  const tabs: Tab[] = [
    'general',
    'workflow',
    'skills',
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
