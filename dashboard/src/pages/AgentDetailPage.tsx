import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  chatUrl,
  createModelConnection,
  createConfigDraftSkillPack,
  deleteConfigDraftSkillPack,
  fetchConfigDraftKnowledgeBinding,
  fetchConfigDraftPublicationConfiguration,
  fetchConfigDraftSkills,
  fetchWorkflowTemplate,
  fetchModelConnections,
  previewWorkflowStageContext,
  publishConfigDraft,
  rollbackConfigVersion,
  updateConfigDraft,
  updateConfigDraftKnowledgeBinding,
  updateConfigDraftSkillPack,
  updateConfigDraftContract,
  updateWorkflowStages,
  validateConfigDraft,
} from '../api/client'
import type {
  AgentKnowledgeReleaseBindingConfiguration,
  BusinessFlowSkillPackConfiguration,
  BusinessFlowSkillPackCreateRequest,
  BusinessFlowSkillPackUpdateRequest,
  DraftAgent,
  DraftKnowledgeReleaseBindingCandidate,
  ProductionAgentPublicationConfiguration,
  SharedModelConnection,
  WorkflowTemplateDescriptor,
} from '../api/types'
import { CodeBlock } from '../components/CodeBlock'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import {
  Badge,
  Button,
  ConfigPanel,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@proofagent/ui'
import { AgentDetailShell } from '../components/agent/AgentDetailShell'
import { AgentMonitor, AgentMonitorSummary } from '../components/agent/AgentMonitor'
import { ModuleEditor } from '../components/agent/ModuleEditor'
import { ModelModuleEditor } from '../components/agent/ModelModuleEditor'
import { MemoryModuleEditor } from '../components/agent/MemoryModuleEditor'
import { KnowledgeModuleEditor } from '../components/agent/KnowledgeModuleEditor'
import type { KnowledgeBindingMutationResult } from '../components/agent/KnowledgeModuleEditor'
import { ReadOnlyConfigurationModule } from '../components/agent/ReadOnlyConfigurationModule'
import { PublicationConfigurationModule } from '../components/agent/PublicationConfigurationModule'
import type { ConfigurationSection } from '../components/agent/ReadOnlyConfigurationModule'
import { SkillsModuleEditor } from '../components/agent/SkillsModuleEditor'
import type { SkillPackMutationResult } from '../components/agent/SkillsModuleEditor'
import { WorkflowModuleEditor } from '../components/agent/WorkflowModuleEditor'
import { ToolsModuleEditor } from '../components/agent/ToolsModuleEditor'
import { ValidateWorkspace } from '../components/agent/ValidateWorkspace'
import { RunDetailDrawer } from '../components/agent/RunDetailDrawer'
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
  replaceToolCapabilityConfiguration,
  updateAgentYamlField,
} from '../utils/agentYaml'

type Tab = 'general' | 'workflow' | 'skills' | 'knowledge' | 'tools' | 'policy' | 'model' | 'memory' | 'response' | 'validate' | 'publication' | 'versions' | 'contract' | 'monitor'

const SAFE_EDITABLE_MODULES: readonly Tab[] = ['general']
const SAFE_LIFECYCLE_TABS: readonly Tab[] = []

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
  const requestedTab = agentDetailTab(searchParams.get('tab'))
  const editableModuleIds = draft?.capabilities?.editable_modules ?? SAFE_EDITABLE_MODULES
  const visibleModuleIds = draft?.capabilities?.visible_modules ?? editableModuleIds
  const advertisedLifecycleTabs = draft?.capabilities?.lifecycle_tabs ?? SAFE_LIFECYCLE_TABS
  const canEditGeneral = draft?.capabilities?.editable_modules.includes('general') ?? false
  const canEditKnowledge = (
    draft?.capabilities?.mode === 'production'
    && editableModuleIds.includes('knowledge')
  )
  const canValidate = draft?.capabilities?.actions.can_validate ?? false
  const canPublish = draft?.capabilities?.actions.can_publish ?? false
  const canRollback = draft?.capabilities?.actions.can_rollback ?? false
  const lifecycleTabIds = advertisedLifecycleTabs.filter(
    (tab) => (
      (tab !== 'validate' || canValidate)
      && (tab !== 'publication' || draft?.capabilities?.mode === 'production')
    ),
  )
  const activeTab = (
    visibleModuleIds.includes(requestedTab) || lifecycleTabIds.includes(requestedTab)
  ) ? requestedTab : 'general'
  const [displayName, setDisplayName] = useState('')
  const [purpose, setPurpose] = useState('')
  const [agentYaml, setAgentYaml] = useState('')
  const [dirtyConfigurationModule, setDirtyConfigurationModule] = useState<Tab | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [modelConnections, setModelConnections] = useState<SharedModelConnection[]>([])
  const [modelConnectionsLoaded, setModelConnectionsLoaded] = useState(false)
  const [workflowDescriptor, setWorkflowDescriptor] = useState<WorkflowTemplateDescriptor | null>(null)
  const [workflowDescriptorError, setWorkflowDescriptorError] = useState<string | null>(null)
  const [skillsConfig, setSkillsConfig] = useState<BusinessFlowSkillPackConfiguration | null>(null)
  const [skillsLoaded, setSkillsLoaded] = useState(false)
  const [skillsError, setSkillsError] = useState<string | null>(null)
  const [knowledgeConfig, setKnowledgeConfig] = useState<AgentKnowledgeReleaseBindingConfiguration | null>(null)
  const [knowledgeLoaded, setKnowledgeLoaded] = useState(false)
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null)
  const [publicationConfiguration, setPublicationConfiguration] = useState<ProductionAgentPublicationConfiguration | null>(null)
  const [publicationConfigurationError, setPublicationConfigurationError] = useState<string | null>(null)
  const [selectedRunDetailId, setSelectedRunDetailId] = useState<string | null>(null)
  const [rollbackTargetVersionId, setRollbackTargetVersionId] = useState<string | null>(null)
  const [rollbackExpectedActiveVersionId, setRollbackExpectedActiveVersionId] = useState<string | null>(null)

  useEffect(() => {
    if (draft) {
      setDisplayName(draft.display_name)
      setPurpose(draft.purpose)
    }
  }, [draft])

  useEffect(() => {
    if (contract) {
      setAgentYaml(contract.agent_yaml)
      setDirtyConfigurationModule(null)
    }
  }, [contract])

  useEffect(() => {
    if (
      activeTab !== 'model'
      || !editableModuleIds.includes('model')
      || modelConnectionsLoaded
    ) return
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
  }, [activeTab, editableModuleIds, modelConnectionsLoaded])

  const workflowTemplateName = useMemo(
    () => readAgentYamlField(agentYaml, ['workflow', 'template']),
    [agentYaml],
  )

  useEffect(() => {
    if (activeTab !== 'workflow' || !editableModuleIds.includes('workflow')) return
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
  }, [activeTab, editableModuleIds, workflowTemplateName, t])

  useEffect(() => {
    if (
      activeTab !== 'skills'
      || !editableModuleIds.includes('skills')
      || skillsLoaded
      || !agentId
      || !draftId
    ) return
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
  }, [activeTab, agentId, draftId, editableModuleIds, skillsLoaded])

  useEffect(() => {
    if (
      activeTab !== 'knowledge'
      || !canEditKnowledge
      || knowledgeLoaded
      || !agentId
      || !draftId
    ) return
    let mounted = true
    fetchConfigDraftKnowledgeBinding(agentId, draftId)
      .then((response) => {
        if (!mounted) return
        setKnowledgeConfig(response)
        setKnowledgeLoaded(true)
        setKnowledgeError(null)
      })
      .catch((err) => {
        if (!mounted) return
        setKnowledgeError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      mounted = false
    }
  }, [activeTab, agentId, canEditKnowledge, draftId, knowledgeLoaded])

  useEffect(() => {
    if (
      activeTab !== 'publication'
      || draft?.capabilities?.mode !== 'production'
      || !agentId
      || !draftId
    ) return
    let mounted = true
    setPublicationConfiguration(null)
    setPublicationConfigurationError(null)
    fetchConfigDraftPublicationConfiguration(agentId, draftId)
      .then((response) => {
        if (!mounted) return
        setPublicationConfiguration(response)
      })
      .catch((err) => {
        if (!mounted) return
        setPublicationConfigurationError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      mounted = false
    }
  }, [activeTab, agentId, draft?.capabilities?.mode, draft?.revision, draftId])

  const latestValidation = draft?.validation_records[draft.validation_records.length - 1]
  const basicsDirty = Boolean(
    draft && (displayName !== draft.display_name || purpose !== draft.purpose),
  )
  const contractDirty = Boolean(
    dirtyConfigurationModule && contract && agentYaml !== contract.agent_yaml,
  )
  const hasUnsavedChanges = basicsDirty || contractDirty
  const latestValidationFresh = Boolean(
    draft && latestValidation && validationCoversCurrentRevision(draft, latestValidation.run_id),
  )
  const memoryReadinessBlockers = useMemo(
    () => memoryConfigurationBlockers(agentYaml, t),
    [agentYaml, t],
  )
  const unsavedValidationBlocker = hasUnsavedChanges
    ? t('agentDetail.unsavedValidationBlocker').replace(
        '{revision}',
        String(draft?.revision ?? t('agentDetail.unknownRevision')),
      )
    : null
  const validationReadinessBlockers = [
    ...memoryReadinessBlockers,
    ...(unsavedValidationBlocker ? [unsavedValidationBlocker] : []),
  ]
  const publicationReadinessBlockers = [
    ...validationReadinessBlockers,
    ...(latestValidation && !latestValidationFresh
      ? [
          t('agentDetail.staleValidationBlocker').replace(
            '{revision}',
            String(draft?.revision ?? t('agentDetail.unknownRevision')),
          ),
        ]
      : []),
  ]

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

  async function runSkillMutation(
    action: () => Promise<void>,
  ): Promise<SkillPackMutationResult> {
    setBusy('skills')
    setActionError(null)
    setStatus(null)
    try {
      await action()
      return 'saved'
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
      if (isConflictError(err) && agentId && draftId) {
        try {
          const latest = await fetchConfigDraftSkills(agentId, draftId)
          setSkillsConfig(latest)
          setSkillsLoaded(true)
          setSkillsError(null)
        } catch (reloadError) {
          setActionError(
            reloadError instanceof Error
              ? `${err instanceof Error ? err.message : String(err)}; reload failed: ${reloadError.message}`
              : `${err instanceof Error ? err.message : String(err)}; reload failed`,
          )
        }
        return 'conflict'
      }
      return 'failed'
    } finally {
      setBusy(null)
    }
  }

  async function runKnowledgeMutation(
    action: () => Promise<void>,
  ): Promise<KnowledgeBindingMutationResult> {
    setBusy('knowledge')
    setActionError(null)
    setStatus(null)
    try {
      await action()
      return 'saved'
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
      if (isConflictError(err) && agentId && draftId) {
        try {
          const latest = await fetchConfigDraftKnowledgeBinding(agentId, draftId)
          setKnowledgeConfig(latest)
          setKnowledgeLoaded(true)
          setKnowledgeError(null)
        } catch (reloadError) {
          setActionError(
            reloadError instanceof Error
              ? `${err instanceof Error ? err.message : String(err)}; reload failed: ${reloadError.message}`
              : `${err instanceof Error ? err.message : String(err)}; reload failed`,
          )
        }
        return 'conflict'
      }
      return 'failed'
    } finally {
      setBusy(null)
    }
  }

  async function saveBasics() {
    if (!agentId || !draftId || !canEditGeneral) return
    if (contractDirty) {
      setActionError(t('agentDetail.saveCurrentModuleFirst'))
      return
    }
    if (!basicsDirty) return
    await runAction('basics', async () => {
      await updateConfigDraft(agentId, draftId, {
        display_name: displayName,
        purpose,
        ...(draft?.revision === undefined ? {} : { expected_revision: draft.revision }),
      })
      setStatus(t('agentDetail.draftFieldsSaved'))
      refresh()
    })
  }

  async function saveAgentYaml(
    module: Tab,
    successMessage = t('agentDetail.configurationSaved'),
  ) {
    if (!agentId || !draftId) return
    if (basicsDirty || (dirtyConfigurationModule && dirtyConfigurationModule !== module)) {
      setActionError(t('agentDetail.saveCurrentModuleFirst'))
      return
    }
    if (!contractDirty) return
    await runAction(module, async () => {
      await updateConfigDraftContract(agentId, draftId, {
        agent_yaml: agentYaml,
        ...(draft?.revision === undefined ? {} : { expected_revision: draft.revision }),
      })
      setDirtyConfigurationModule(null)
      setStatus(successMessage)
      refresh()
    })
  }

  async function saveWorkflowStages(payload: Parameters<typeof updateWorkflowStages>[2]) {
    if (!agentId || !draftId) return
    if (basicsDirty || (contractDirty && dirtyConfigurationModule !== 'workflow')) {
      setActionError(t('agentDetail.saveCurrentModuleFirst'))
      return
    }
    await runAction('workflow-stages', async () => {
      const updated = await updateWorkflowStages(agentId, draftId, {
        ...payload,
        ...(draft?.revision === undefined
          ? {}
          : { expected_revision: draft.revision }),
      })
      setAgentYaml(updated.agent_yaml)
      setDirtyConfigurationModule(null)
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
    if (!agentId || !draftId) return 'failed' as const
    if (hasUnsavedChanges) {
      setActionError(t('agentDetail.saveCurrentModuleFirst'))
      return 'failed' as const
    }
    return runSkillMutation(async () => {
      const expectedRevision = skillsConfig?.revision ?? draft?.revision
      const updated = await createConfigDraftSkillPack(agentId, draftId, {
        ...payload,
        ...(expectedRevision === undefined
          ? {}
          : { expected_revision: expectedRevision }),
      })
      setSkillsConfig(updated)
      setSkillsLoaded(true)
      setSkillsError(null)
      setStatus(t('agentDetail.skillPackCreated'))
      refresh()
    })
  }

  async function updateSkillPack(packId: string, payload: BusinessFlowSkillPackUpdateRequest) {
    if (!agentId || !draftId) return 'failed' as const
    if (hasUnsavedChanges) {
      setActionError(t('agentDetail.saveCurrentModuleFirst'))
      return 'failed' as const
    }
    return runSkillMutation(async () => {
      const expectedRevision = skillsConfig?.revision ?? draft?.revision
      const updated = await updateConfigDraftSkillPack(agentId, draftId, packId, {
        ...payload,
        ...(expectedRevision === undefined
          ? {}
          : { expected_revision: expectedRevision }),
      })
      setSkillsConfig(updated)
      setSkillsLoaded(true)
      setSkillsError(null)
      setStatus(t('agentDetail.skillPackSaved'))
      refresh()
    })
  }

  async function deleteSkillPack(packId: string) {
    if (!agentId || !draftId) return 'failed' as const
    if (hasUnsavedChanges) {
      setActionError(t('agentDetail.saveCurrentModuleFirst'))
      return 'failed' as const
    }
    return runSkillMutation(async () => {
      const expectedRevision = skillsConfig?.revision ?? draft?.revision
      const updated = await deleteConfigDraftSkillPack(
        agentId,
        draftId,
        packId,
        expectedRevision,
      )
      setSkillsConfig(updated)
      setSkillsLoaded(true)
      setSkillsError(null)
      setStatus(t('agentDetail.skillPackDeleted'))
      refresh()
    })
  }

  async function saveKnowledgeReleaseBinding(
    candidate: DraftKnowledgeReleaseBindingCandidate,
  ): Promise<KnowledgeBindingMutationResult> {
    if (!agentId || !draftId || !knowledgeConfig) return 'failed'
    if (hasUnsavedChanges) {
      setActionError(t('agentDetail.saveCurrentModuleFirst'))
      return 'failed'
    }
    return runKnowledgeMutation(async () => {
      const updated = await updateConfigDraftKnowledgeBinding(agentId, draftId, {
        expected_revision: knowledgeConfig.revision,
        ...candidate,
      })
      setKnowledgeConfig(updated)
      setKnowledgeLoaded(true)
      setKnowledgeError(null)
      setStatus(t('agentDetail.knowledgeBindingSaved'))
      refresh()
    })
  }

  async function publishDraft() {
    if (
      !agentId
      || !draftId
      || !latestValidation
      || !latestValidationFresh
      || publicationReadinessBlockers.length > 0
    ) return
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
    if (path[0] === 'capabilities' && path[1] === 'tools') {
      return replaceToolCapabilityConfiguration(current, path, value)
    }
    return updateAgentYamlField(current, path, value)
  }

  async function confirmRollback() {
    const versionId = rollbackTargetVersionId
    if (!agentId) return
    if (!versionId) return
    await runAction(`rollback-${versionId}`, async () => {
      await rollbackConfigVersion(agentId, versionId, rollbackExpectedActiveVersionId)
      setStatus(t('agentDetail.activeVersionSet').replace('{version}', versionId))
      refreshVersions()
      setRollbackTargetVersionId(null)
      setRollbackExpectedActiveVersionId(null)
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
  ].filter((module) => visibleModuleIds.includes(module.id as Tab))

  const LIFECYCLE_TABS = [
    { id: 'validate', label: t('agentDetail.tabValidate') },
    { id: 'publication', label: t('agentDetail.tabPublication') },
    { id: 'versions', label: t('agentDetail.tabVersions') },
    { id: 'contract', label: t('agentDetail.tabContract') },
    { id: 'monitor', label: t('agentDetail.tabMonitor') },
  ].filter((tab) => lifecycleTabIds.includes(tab.id as Tab))

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

  function readOnlyConfiguration(
    title: string,
    sections: ConfigurationSection[],
  ) {
    return (
      <ReadOnlyConfigurationModule
        title={title}
        description={t(
          draft?.capabilities?.mode === 'production'
            ? 'agentDetail.readOnlyConfigurationDescription'
            : 'agentDetail.contractProjectionDescription',
        )}
        status={t(
          draft?.capabilities?.mode === 'production'
            ? 'agentDetail.readOnlyConfiguration'
            : 'agentDetail.contractProjection',
        )}
        agentYaml={agentYaml}
        sections={sections}
        emptyMessage={t('agentDetail.configurationNotSet')}
      />
    )
  }

  return (
    <AgentDetailShell
      agentName={displayName}
      modules={CONFIGURE_MODULES}
      lifecycle={LIFECYCLE_TABS}
      activeModule={activeTab}
      onModuleChange={setActiveTab}
    >
      <section
        aria-label={t('agentDetail.configurationFlow')}
        className="mb-5 flex flex-col gap-3 border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3 md:flex-row md:items-center md:justify-between"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              {t('agentDetail.configurationFlow')}
            </span>
            <Badge variant="outline">
              {t('agentDetail.draftRevisionValue').replace(
                '{revision}',
                String(draft.revision ?? t('agentDetail.unknownRevision')),
              )}
            </Badge>
            <Badge variant={hasUnsavedChanges ? 'warning' : 'success'}>
              {t(
                hasUnsavedChanges
                  ? 'agentDetail.unsavedConfiguration'
                  : 'agentDetail.savedConfiguration',
              )}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            {t('agentDetail.configurationFlowDescription')}
          </p>
        </div>
        {latestValidation && (
          <Badge variant={latestValidationFresh ? 'success' : 'warning'} className="w-fit shrink-0">
            {t(
              latestValidationFresh
                ? 'agentDetail.validationCurrent'
                : 'agentDetail.validationStale',
            )}
          </Badge>
        )}
      </section>

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
              {canEditGeneral && (
                <button
                  onClick={saveBasics}
                  disabled={busy === 'basics'}
                  className="w-fit rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                >
                  {busy === 'basics' ? t('agentDetail.saving') : t('agentDetail.save')}
                </button>
              )}
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
                    disabled={!canEditGeneral}
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
                    disabled={!canEditGeneral}
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
              draftValidationCount={draft.validation_records.length}
              onOpenRunDetail={setSelectedRunDetailId}
            />
          )}
        </div>
      )}

      {activeTab === 'workflow' && (
        editableModuleIds.includes('workflow') ? (
          <WorkflowModuleEditor
            agentYaml={agentYaml}
            descriptor={workflowDescriptor}
            descriptorError={workflowDescriptorError}
            onFieldChange={(path, value) => {
              setDirtyConfigurationModule('workflow')
              setAgentYaml((current: string) => updateAgentYamlField(current, path, value))
            }}
            onSaveCore={() => saveAgentYaml('workflow', t('agentDetail.workflowSaved'))}
            onSaveStages={saveWorkflowStages}
            onPreviewStage={previewWorkflowStage}
            busy={busy === 'workflow'}
            stageBusy={busy === 'workflow-stages'}
          />
        ) : readOnlyConfiguration(t('agentDetail.tabWorkflow'), [
          { label: 'workflow', path: ['workflow'] },
        ])
      )}

      {activeTab === 'skills' && (
        editableModuleIds.includes('skills') ? (
          <SkillsModuleEditor
            config={skillsConfig}
            loading={!skillsLoaded && !skillsError}
            error={skillsError}
            busy={busy === 'skills'}
            onCreatePack={createSkillPack}
            onUpdatePack={updateSkillPack}
            onDeletePack={deleteSkillPack}
          />
        ) : readOnlyConfiguration(t('agentDetail.tabSkills'), [
          { label: 'capabilities.skills', path: ['capabilities', 'skills'] },
        ])
      )}

      {activeTab === 'knowledge' && (
        canEditKnowledge ? (
          <KnowledgeModuleEditor
            config={knowledgeConfig}
            loading={!knowledgeLoaded && !knowledgeError}
            error={knowledgeError}
            busy={busy === 'knowledge'}
            onSave={saveKnowledgeReleaseBinding}
          />
        ) : readOnlyConfiguration(
          t('agentDetail.tabKnowledge'),
          [
            { label: 'package_knowledge_sources', path: ['package_knowledge_sources'] },
            { label: 'knowledge_bindings', path: ['knowledge_bindings'] },
            { label: 'retrieval', path: ['retrieval'] },
          ],
        )
      )}

      {activeTab === 'tools' && (
        editableModuleIds.includes('tools') ? (
          <ToolsModuleEditor
            agentYaml={agentYaml}
            onFieldChange={(path, value) => {
              setDirtyConfigurationModule('tools')
              setAgentYaml((current: string) => updateConfigurationYamlField(current, path, value))
            }}
            onSave={() => saveAgentYaml('tools', t('agentDetail.toolsSaved'))}
            busy={busy === 'tools'}
          />
        ) : readOnlyConfiguration(t('agentDetail.tabTools'), [
          { label: 'capabilities.tools', path: ['capabilities', 'tools'] },
          { label: 'tools.yaml', content: contract.tools_yaml },
        ])
      )}

      {activeTab === 'policy' && (
        editableModuleIds.includes('policy') ? (
          <ModuleEditor
            title={t('agentDetail.policyTitle')}
            description={t('agentDetail.policyDescription')}
            fields={POLICY_FIELDS}
            yamlSection="policy"
            agentYaml={agentYaml}
            onFieldChange={(path, value) => {
              setDirtyConfigurationModule('policy')
              setAgentYaml((current: string) => updateAgentYamlField(current, path, value))
            }}
            onSave={() => saveAgentYaml('policy', t('agentDetail.policySaved'))}
            busy={busy === 'policy'}
          />
        ) : readOnlyConfiguration(t('agentDetail.tabPolicy'), [
          { label: 'policy', path: ['policy'] },
          { label: 'policy.yaml', content: contract.policy_yaml },
        ])
      )}

      {activeTab === 'model' && (
        editableModuleIds.includes('model') ? (
          <ModelModuleEditor
            agentYaml={agentYaml}
            modelConnections={modelConnections}
            onFieldChange={(path, value) => {
              setDirtyConfigurationModule('model')
              setAgentYaml((current: string) => updateConfigurationYamlField(current, path, value))
            }}
            onModelConfigChange={(path, value) => {
              setDirtyConfigurationModule('model')
              setAgentYaml((current: string) => replaceAgentYamlMapping(current, path, value))
            }}
            onCreateSharedModelConnection={async (payload) => {
              const connection = await createModelConnection(payload)
              setModelConnections((current) => [...current, connection])
              return connection
            }}
            onSave={() => saveAgentYaml('model', t('agentDetail.modelSaved'))}
            busy={busy === 'model'}
          />
        ) : readOnlyConfiguration(t('agentDetail.tabModel'), [
          { label: 'model', path: ['model'] },
          { label: 'react.planner', path: ['react', 'planner'] },
          { label: 'review.subagent', path: ['review', 'subagent'] },
        ])
      )}

      {activeTab === 'memory' && (
        editableModuleIds.includes('memory') ? (
          <MemoryModuleEditor
            agentYaml={agentYaml}
            onFieldChange={(path, value) => {
              setDirtyConfigurationModule('memory')
              setAgentYaml((current: string) => updateConfigurationYamlField(current, path, value))
            }}
            onSave={() => saveAgentYaml('memory', t('agentDetail.memorySaved'))}
            busy={busy === 'memory'}
          />
        ) : readOnlyConfiguration(t('agentDetail.tabMemory'), [
          { label: 'capabilities.memory', path: ['capabilities', 'memory'] },
          {
            label: 'context.source_policies.memory_recall',
            path: ['context', 'source_policies', 'memory_recall'],
          },
        ])
      )}

      {activeTab === 'response' && (
        editableModuleIds.includes('response') ? (
          <ModuleEditor
            title={t('agentDetail.responseTitle')}
            description={t('agentDetail.responseDescription')}
            fields={RESPONSE_FIELDS}
            yamlSection="response"
            agentYaml={agentYaml}
            onFieldChange={(path, value) => {
              setDirtyConfigurationModule('response')
              setAgentYaml((current: string) => updateAgentYamlField(current, path, value))
            }}
            onSave={() => saveAgentYaml('response', t('agentDetail.responseSaved'))}
            busy={busy === 'response'}
          />
        ) : readOnlyConfiguration(t('agentDetail.tabResponse'), [
          { label: 'response', path: ['response'] },
        ])
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
          readinessBlockers={validationReadinessBlockers}
        />
      )}

      {activeTab === 'versions' && (
        <ConfigPanel
          headingLevel={3}
          title={t('agentDetail.publishedVersions')}
          description={activeVersionId ?? t('agentDetail.noActiveVersion')}
          actions={canPublish ? (
            <Button
              variant="outline"
              size="sm"
              onClick={publishDraft}
              disabled={busy === 'publish' || !latestValidationFresh || publicationReadinessBlockers.length > 0}
            >
              {t('agentDetail.publish')}
            </Button>
          ) : undefined}
        >
          {canPublish && publicationReadinessBlockers.length > 0 && (
            <BlockingReasons title={t('validate.readinessBlocked')} reasons={publicationReadinessBlockers} />
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
                    ) : canRollback ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setRollbackExpectedActiveVersionId(activeVersionId)
                          setRollbackTargetVersionId(version.version_id)
                        }}
                        disabled={busy === `rollback-${version.version_id}`}
                        className="shrink-0"
                      >
                        {t('agentDetail.rollback')}
                      </Button>
                    ) : null}
                  </div>
                )
              })}
            </div>
          )}
        </ConfigPanel>
      )}

      {activeTab === 'publication' && (
        <PublicationConfigurationModule
          configuration={publicationConfiguration}
          loading={!publicationConfiguration && !publicationConfigurationError}
          error={publicationConfigurationError}
          onNavigate={setActiveTab}
        />
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
        <AgentMonitor
          agentId={agentId}
          draftValidationCount={draft.validation_records.length}
          onOpenRunDetail={setSelectedRunDetailId}
        />
      )}

      <Dialog
        open={rollbackTargetVersionId !== null}
        onOpenChange={(open) => {
          if (!open && !busy?.startsWith('rollback-')) {
            setRollbackTargetVersionId(null)
            setRollbackExpectedActiveVersionId(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('agentDetail.rollbackConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {t('agentDetail.rollbackConfirmDescription')}
            </DialogDescription>
          </DialogHeader>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div className="border border-[var(--border)] bg-[var(--bg-base)] p-3">
              <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {t('agentDetail.rollbackCurrentVersion')}
              </dt>
              <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">
                {rollbackExpectedActiveVersionId ?? t('agentDetail.noActiveVersion')}
              </dd>
            </div>
            <div className="border border-[var(--border)] bg-[var(--bg-base)] p-3">
              <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {t('agentDetail.rollbackTargetVersion')}
              </dt>
              <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">
                {rollbackTargetVersionId}
              </dd>
            </div>
          </dl>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setRollbackTargetVersionId(null)
                setRollbackExpectedActiveVersionId(null)
              }}
              disabled={Boolean(busy?.startsWith('rollback-'))}
            >
              {t('agentDetail.rollbackCancel')}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={confirmRollback}
              disabled={!rollbackTargetVersionId || Boolean(busy?.startsWith('rollback-'))}
            >
              {busy?.startsWith('rollback-')
                ? t('agentDetail.rollbackRunning')
                : t('agentDetail.rollbackConfirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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

function isConflictError(error: unknown): error is { status: 409 } {
  return typeof error === 'object' && error !== null && 'status' in error && error.status === 409
}

function validationCoversCurrentRevision(draft: DraftAgent, runId: string): boolean {
  if (draft.revision === undefined) return false
  const latestOperation = draft.operation_audit[draft.operation_audit.length - 1]
  const validatedRevision = latestOperation?.metadata.draft_revision
  return Boolean(
    latestOperation
    && latestOperation.operation === 'validated'
    && latestOperation.metadata.run_id === runId
    && typeof validatedRevision === 'number'
    && validatedRevision + 1 === draft.revision,
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
    'publication',
    'versions',
    'contract',
    'monitor',
  ]
  return value && tabs.includes(value as Tab) ? (value as Tab) : 'general'
}
