import { useEffect, useMemo, useState } from 'react'
import type {
  WorkflowStageConfig,
  WorkflowStageContextPreview,
  WorkflowStageDescriptor,
  WorkflowStagePromptConfig,
  WorkflowTemplateDescriptor,
} from '../../api/types'
import { CodeBlock } from '../CodeBlock'
import {
  readAgentYamlField,
  readWorkflowStageConfigs,
  replaceWorkflowStages,
} from '../../utils/agentYaml'
import { WORKFLOW_FIELDS, WORKFLOW_TEMPLATE_FALLBACK } from './module-configs/workflow'
import { useWorkflowTemplates } from '../../hooks/useWorkflowTemplates'
import { useLocale } from '../../i18n/locale'

interface WorkflowModuleEditorProps {
  agentYaml: string
  descriptor: WorkflowTemplateDescriptor | null
  descriptorError?: string | null
  onFieldChange: (path: string[], value: string) => void
  onSaveCore: () => void
  onSaveStages: (payload: {
    template_descriptor_version: string
    stages: WorkflowStageConfig[]
  }) => Promise<void>
  onPreviewStage: (
    stageId: string,
    payload: {
      prompt: WorkflowStagePromptConfig
      context: Record<string, boolean>
    },
  ) => Promise<WorkflowStageContextPreview>
  busy: boolean
  stageBusy: boolean
}

export function WorkflowModuleEditor({
  agentYaml,
  descriptor,
  descriptorError,
  onFieldChange,
  onSaveCore,
  onSaveStages,
  onPreviewStage,
  busy,
  stageBusy,
}: WorkflowModuleEditorProps) {
  const { t } = useLocale()
  // Template options come from the Dynamic Workflow Template Catalog, falling
  // back to the static list when the catalog fails to load (Template Selector
  // Fallback) so the selector is never empty.
  const { templates: catalogTemplates, names: catalogTemplateNames } =
    useWorkflowTemplates()
  const templateOptions = catalogTemplateNames.length
    ? catalogTemplateNames
    : WORKFLOW_TEMPLATE_FALLBACK
  const [showYaml, setShowYaml] = useState(false)
  const [selectedStageId, setSelectedStageId] = useState('')
  const [stages, setStages] = useState<WorkflowStageConfig[]>([])
  const [preview, setPreview] = useState<WorkflowStageContextPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)

  useEffect(() => {
    if (!descriptor) {
      setStages([])
      setSelectedStageId('')
      return
    }
    const configuredById = new Map(
      readWorkflowStageConfigs(agentYaml).map((stage) => [stage.id, stage]),
    )
    const nextStages = descriptor.stages.map((stage) => {
      const configured = configuredById.get(stage.id)
      return configured
        ? normalizeStageConfig(configured)
        : emptyStageConfig(stage.id)
    })
    setStages(nextStages)
    setSelectedStageId((current) => (
      current && descriptor.stages.some((stage) => stage.id === current)
        ? current
        : descriptor.stages[0]?.id ?? ''
    ))
  }, [agentYaml, descriptor])

  useEffect(() => {
    setPreview(null)
    setPreviewError(null)
  }, [selectedStageId])

  const selectedDescriptor = descriptor?.stages.find((stage) => stage.id === selectedStageId) ?? null
  const selectedConfig = stages.find((stage) => stage.id === selectedStageId) ?? null
  const canEditPrompt = Boolean(selectedDescriptor?.editable_prompt_fields.length)
  const canConfigureContext = Boolean(selectedDescriptor?.context_options.length)
  const canPreviewSelected = canEditPrompt || canConfigureContext
  const workflowTemplate = readAgentYamlField(agentYaml, ['workflow', 'template']) || descriptor?.name || t('workflow.notConfigured')
  const usesCompatibilityTemplate = workflowTemplate === 'enterprise_qa'
  const workflowRuntime = readAgentYamlField(agentYaml, ['workflow', 'runtime']) || t('workflow.notConfigured')
  const checkpointerProvider = (
    readAgentYamlField(agentYaml, ['workflow', 'checkpointer', 'provider'])
    || readAgentYamlField(agentYaml, ['workflow', 'checkpointer', 'type'])
    || t('workflow.notConfigured')
  )
  const stageCount = descriptor?.stages.length ?? 0
  const modelBearingStageCount = descriptor?.stages.filter((stage) => stage.model_bearing).length ?? 0
  const editableStageCount = descriptor?.stages.filter((stage) => stage.editable_prompt_fields.length > 0).length ?? 0
  const localYaml = descriptor
    ? replaceWorkflowStages(agentYaml, descriptor.descriptor_version, stages)
    : agentYaml

  const stageLabelById = useMemo(() => {
    const labels = new Map<string, string>()
    for (const stage of descriptor?.stages ?? []) labels.set(stage.id, stage.label)
    return labels
  }, [descriptor])
  const stageGroups = useMemo(
    () => groupWorkflowStages(descriptor?.stages ?? []),
    [descriptor],
  )

  function updateSelectedStage(updater: (stage: WorkflowStageConfig) => WorkflowStageConfig) {
    if (!selectedConfig) return
    setStages((current) => current.map((stage) => (
      stage.id === selectedConfig.id ? updater(stage) : stage
    )))
  }

  async function saveStages() {
    if (!descriptor) return
    // The descriptor_version sent with stages must match the currently selected
    // Template (the value being persisted by the core save), NOT the descriptor
    // prop, which can describe a previously-loaded template after the dropdown
    // changes. Resolve it from the catalog by the selected template name; fall
    // back to the loaded descriptor's version when the catalog lacks an entry.
    const selectedTemplateName = workflowTemplate
    const catalogDescriptorVersion =
      catalogTemplates.find((entry) => entry.name === selectedTemplateName)
        ?.descriptor_version ?? null
    const descriptorVersion =
      catalogDescriptorVersion ?? descriptor.descriptor_version
    await onSaveStages({
      template_descriptor_version: descriptorVersion,
      stages: stages.map((stage) => sanitizeStageConfigForDescriptor(stage, descriptor)),
    })
  }

  async function previewSelectedStage() {
    if (!selectedConfig) return
    setPreviewBusy(true)
    setPreviewError(null)
    try {
      const result = await onPreviewStage(selectedConfig.id, {
        prompt: selectedConfig.prompt,
        context: selectedConfig.context,
      })
      setPreview(result)
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err))
    } finally {
      setPreviewBusy(false)
    }
  }

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--border)] p-5">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {t('workflow.design')}
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            {descriptor?.description ?? t('workflow.descriptorFallback')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => setShowYaml(!showYaml)}
            className={`text-xs font-medium px-3 py-1.5 rounded-md transition-colors ${
              showYaml
                ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
            }`}
          >
            {showYaml ? t('moduleEditor.hideYaml') : t('workflow.advancedYaml')}
          </button>
          <button
            onClick={onSaveCore}
            disabled={busy}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {busy ? t('agentDetail.saving') : t('workflow.saveCore')}
          </button>
          <button
            onClick={saveStages}
            disabled={stageBusy || !descriptor || !descriptor.name.startsWith('react_enterprise_qa')}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {stageBusy ? t('agentDetail.saving') : t('workflow.saveStages')}
          </button>
        </div>
      </div>

      <section
        aria-label={t('workflow.templateSummary')}
        className="border-b border-[var(--border)] p-5"
      >
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              {t('workflow.template')}
            </h4>
            <p className="mt-1 text-sm text-[var(--text-primary)]">
              {workflowTemplate}
            </p>
          </div>
          {descriptor && (
            <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs text-[var(--text-secondary)]">
              {descriptor.descriptor_version}
            </span>
          )}
        </div>
        <dl className="grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-5">
          <SummaryItem label="Runtime" value={workflowRuntime} />
          <SummaryItem label={t('workflow.checkpointer')} value={checkpointerProvider} />
          <SummaryItem label={t('workflow.stages')} value={t('workflow.stagesCount').replace('{count}', String(stageCount))} />
          <SummaryItem label={t('workflow.modelBearing')} value={String(modelBearingStageCount)} />
          <SummaryItem label={t('workflow.editable')} value={String(editableStageCount)} />
        </dl>
        {usesCompatibilityTemplate && (
          <div className="mt-4 rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3 text-sm text-[var(--text-secondary)]">
            <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              {t('workflow.compatibilityTemplate')}
            </div>
            <p className="mt-1">
              {t('workflow.compatibilityDescription')}
            </p>
          </div>
        )}
      </section>

      {showYaml && (
        <div className="border-b border-[var(--border)] p-5">
          <CodeBlock>{localYaml}</CodeBlock>
        </div>
      )}

      <div className="border-b border-[var(--border)] p-5">
        <div className="grid gap-4 md:grid-cols-4">
          {WORKFLOW_FIELDS.map((field) => {
            // The Template selector uses the dynamic catalog (or its static
            // fallback) instead of a hardcoded field.options list.
            const fieldOptions =
              field.path.join('.') === 'workflow.template'
                ? templateOptions
                : field.options
            return (
            <div key={field.path.join('.')} className="block">
              <FieldHeader
                label={field.label}
                help={workflowFieldHelp(field.path.join('.'))}
              />
              {field.input === 'select' && fieldOptions ? (
                <select
                  aria-label={field.label}
                  value={readAgentYamlField(agentYaml, field.path)}
                  onChange={(event) => onFieldChange(field.path, event.target.value)}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                >
                  {fieldOptions.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              ) : (
                <input
                  aria-label={field.label}
                  type={field.input}
                  value={readAgentYamlField(agentYaml, field.path)}
                  onChange={(event) => onFieldChange(field.path, event.target.value)}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                />
              )}
            </div>
            )
          })}
        </div>
      </div>

      {descriptorError && (
        <div className="border-b border-[var(--border)] p-5 text-sm text-[var(--danger)]">
          {descriptorError}
        </div>
      )}

      <div className="grid gap-0 lg:grid-cols-[280px_minmax(0,1fr)]">
        <section className="border-b border-[var(--border)] bg-[var(--bg-base)] p-4 lg:border-b-0 lg:border-r">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Read-Only Relationship Map
              </h4>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                {descriptor?.descriptor_version ?? 'Descriptor not loaded'}
              </p>
            </div>
            {descriptor && (
              <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs text-[var(--text-secondary)]">
                {descriptor.stages.length} stages
              </span>
            )}
          </div>

          {!descriptor ? (
            <p className="text-sm text-[var(--text-muted)]">No workflow descriptor available.</p>
          ) : (
            <div className="space-y-4">
              {stageGroups.map((group) => (
                <div key={group.title}>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <h5 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      {group.title}
                    </h5>
                    <span className="text-[11px] text-[var(--text-muted)]">{group.stages.length}</span>
                  </div>
                  <div className="space-y-1">
                    {group.stages.map((stage, index) => (
                      <WorkflowMapStage
                        key={stage.id}
                        stage={stage}
                        selected={stage.id === selectedStageId}
                        stageLabelById={stageLabelById}
                        isLast={index === group.stages.length - 1}
                        onSelect={() => setSelectedStageId(stage.id)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section aria-label="Stage Inspector" className="p-5">
          {!selectedDescriptor || !selectedConfig ? (
            <p className="text-sm text-[var(--text-muted)]">Select a workflow stage.</p>
          ) : (
            <div className="space-y-5">
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Stage Inspector
                </h4>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  Review the selected stage before editing bounded prompt and context fields.
                </p>
              </div>

              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h4 className="text-base font-semibold text-[var(--text-primary)]">
                    {selectedDescriptor.label}
                  </h4>
                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    {selectedDescriptor.description}
                  </p>
                </div>
                <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs text-[var(--text-secondary)]">
                  {selectedDescriptor.model_bearing ? 'Model-bearing' : 'Governed'}
                </span>
              </div>

              <dl className="grid gap-3 text-xs text-[var(--text-muted)] sm:grid-cols-3">
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Stage ID
                  </dt>
                  <dd className="mt-1 font-mono text-[var(--text-primary)]">
                    {selectedDescriptor.id}
                  </dd>
                </div>
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Availability
                  </dt>
                  <dd className="mt-1 text-[var(--text-primary)]">
                    {selectedDescriptor.required ? 'Required' : 'Optional'}
                  </dd>
                </div>
                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <dt className="font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Editable prompt fields
                  </dt>
                  <dd className="mt-2 flex flex-wrap gap-1.5 font-mono text-[var(--text-primary)]">
                    {selectedDescriptor.editable_prompt_fields.length > 0 ? (
                      selectedDescriptor.editable_prompt_fields.map((field) => (
                        <span
                          key={field}
                          className="rounded bg-[var(--bg-hover)] px-2 py-0.5"
                        >
                          {field}
                        </span>
                      ))
                    ) : (
                      <span>None</span>
                    )}
                  </dd>
                </div>
              </dl>

              <div className="grid gap-3 text-xs text-[var(--text-muted)] sm:grid-cols-2">
                <div>
                  <span className="font-semibold text-[var(--text-secondary)]">Input</span>
                  <p className="mt-1">{selectedDescriptor.input_summary || 'Governed runtime input.'}</p>
                </div>
                <div>
                  <span className="font-semibold text-[var(--text-secondary)]">Output</span>
                  <p className="mt-1">{selectedDescriptor.output_summary || 'Governed runtime output.'}</p>
                </div>
              </div>

              <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3 text-xs text-[var(--text-secondary)]">
                Harness-owned prompt is locked. Stage Prompt is appended only as Business Context Addendum.
              </div>

              <div className="block">
                <FieldHeader
                  label="Business Context"
                  help="Adds domain-specific context to this stage without replacing the harness-owned control prompt. Use it for policy scope, business rules, and stage-specific operating context."
                />
                <textarea
                  aria-label="Business Context"
                  value={selectedConfig.prompt.business_context ?? ''}
                  disabled={!canEditPrompt}
                  onChange={(event) => updateSelectedStage((stage) => ({
                    ...stage,
                    prompt: { ...stage.prompt, business_context: event.target.value },
                  }))}
                  rows={4}
                  className="w-full resize-y bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-60"
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="block">
                  <FieldHeader
                    label="Task Instructions"
                    help="Adds short, line-by-line instructions for how this stage should perform its task. Each non-empty line is saved as one instruction."
                  />
                  <textarea
                    aria-label="Task Instructions"
                    value={selectedConfig.prompt.task_instructions.join('\n')}
                    disabled={!canEditPrompt}
                    onChange={(event) => updateSelectedStage((stage) => ({
                      ...stage,
                      prompt: {
                        ...stage.prompt,
                        task_instructions: splitLines(event.target.value),
                      },
                    }))}
                    rows={5}
                    className="w-full resize-y bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-60"
                  />
                </div>
                <div className="block">
                  <FieldHeader
                    label="Output Preferences"
                    help="Controls how this stage should shape its output, such as evidence style, formatting preferences, or response constraints. Each non-empty line is saved separately."
                  />
                  <textarea
                    aria-label="Output Preferences"
                    value={selectedConfig.prompt.output_preferences.join('\n')}
                    disabled={!canEditPrompt}
                    onChange={(event) => updateSelectedStage((stage) => ({
                      ...stage,
                      prompt: {
                        ...stage.prompt,
                        output_preferences: splitLines(event.target.value),
                      },
                    }))}
                    rows={5}
                    className="w-full resize-y bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-60"
                  />
                </div>
              </div>

              {selectedDescriptor.context_options.length > 0 && (
                <div>
                  <FieldHeader
                    label="Context Options"
                    help="Toggles structured runtime context that the harness can safely provide to this stage, such as Agent purpose or prior outcome state."
                  />
                  <div className="grid gap-2 sm:grid-cols-2">
                    {selectedDescriptor.context_options.map((option) => (
                      <label
                        key={option}
                        className="flex items-center gap-2 text-sm text-[var(--text-secondary)]"
                      >
                        <input
                          type="checkbox"
                          checked={Boolean(selectedConfig.context[option])}
                          disabled={!canConfigureContext}
                          onChange={(event) => updateSelectedStage((stage) => ({
                            ...stage,
                            context: {
                              ...stage.context,
                              [option]: event.target.checked,
                            },
                          }))}
                          className="h-4 w-4 rounded border-[var(--border)] bg-[var(--bg-base)]"
                        />
                        <span className="font-mono text-xs">{option}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={previewSelectedStage}
                  disabled={previewBusy || !canPreviewSelected}
                  className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                >
                  {previewBusy ? 'Previewing...' : 'Preview Context'}
                </button>
                {previewError && (
                  <span className="text-sm text-[var(--danger)]">{previewError}</span>
                )}
              </div>

              {preview && (
                <div className="space-y-3">
                  <div>
                    <h5 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      Business Context Addendum
                    </h5>
                    <CodeBlock>{preview.business_context_addendum.text || 'No addendum configured.'}</CodeBlock>
                  </div>
                  <div>
                    <h5 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      Structured Control Context
                    </h5>
                    <CodeBlock>{JSON.stringify(preview.structured_control_context, null, 2)}</CodeBlock>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </dt>
      <dd className="mt-1 break-words font-mono text-xs text-[var(--text-primary)]">
        {value}
      </dd>
    </div>
  )
}

function WorkflowMapStage({
  stage,
  selected,
  stageLabelById,
  isLast,
  onSelect,
}: {
  stage: WorkflowStageDescriptor
  selected: boolean
  stageLabelById: Map<string, string>
  isLast: boolean
  onSelect: () => void
}) {
  return (
    <div className="relative pl-5">
      <span className={`absolute left-1 top-4 h-full w-px bg-[var(--border)] ${isLast ? 'hidden' : ''}`} />
      <span className={`absolute left-0 top-3 h-3 w-3 rounded-full border ${
        selected
          ? 'border-[var(--accent)] bg-[var(--accent)]'
          : 'border-[var(--border)] bg-[var(--bg-surface)]'
      }`} />
      <button
        type="button"
        onClick={onSelect}
        className={`w-full cursor-pointer rounded-md border px-3 py-2 text-left transition-colors ${
          selected
            ? 'border-[var(--accent)] bg-[var(--accent)]/10'
            : 'border-[var(--border)] bg-[var(--bg-surface)] hover:bg-[var(--bg-hover)]'
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-[var(--text-primary)]">{stage.label}</div>
            <div className="mt-0.5 truncate font-mono text-[11px] text-[var(--text-muted)]">{stage.id}</div>
          </div>
          <span className="shrink-0 rounded-full bg-[var(--bg-hover)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
            {stage.model_bearing ? 'model' : 'stage'}
          </span>
        </div>
        <div className="mt-2 truncate text-[11px] text-[var(--text-muted)]">
          <span className="font-semibold text-[var(--text-secondary)]">Next: </span>
          {formatSuccessors(stage, stageLabelById)}
        </div>
        {stage.governed_handoff_points.length > 0 && (
          <div className="mt-1 truncate text-[11px] text-[var(--text-muted)]">
            <span className="font-semibold text-[var(--text-secondary)]">Handoff: </span>
            {stage.governed_handoff_points.join(', ')}
          </div>
        )}
      </button>
    </div>
  )
}

function FieldHeader({ label, help }: { label: string; help: string }) {
  const [open, setOpen] = useState(false)

  return (
    <span className="relative mb-2 flex items-center gap-1.5">
      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <button
        type="button"
        aria-label={`Explain ${label}`}
        aria-expanded={open}
        onClick={(event) => {
          event.preventDefault()
          setOpen((current) => !current)
        }}
        className="inline-flex h-4 w-4 cursor-pointer items-center justify-center rounded-full border border-[var(--border)] text-[10px] font-semibold text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
      >
        ?
      </button>
      {open && (
        <span
          role="note"
          className="absolute left-0 top-6 z-20 w-72 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-3 text-xs normal-case leading-5 tracking-normal text-[var(--text-secondary)] shadow-lg"
        >
          {help}
        </span>
      )}
    </span>
  )
}

function groupWorkflowStages(stages: WorkflowStageDescriptor[]) {
  const visited = new Set<string>()
  const ordered = topologicalWorkflowStages(stages)
  const groups = [
    {
      title: 'Entry',
      stages: ordered.filter((stage) => stage.predecessors.length === 0),
    },
    {
      title: 'Processing',
      stages: ordered.filter((stage) => stage.predecessors.length > 0 && stage.successors.length > 0),
    },
    {
      title: 'Terminal',
      stages: ordered.filter((stage) => stage.successors.length === 0),
    },
  ].map((group) => ({
    ...group,
    stages: group.stages.filter((stage) => {
      if (visited.has(stage.id)) return false
      visited.add(stage.id)
      return true
    }),
  }))

  return groups.filter((group) => group.stages.length > 0)
}

function topologicalWorkflowStages(stages: WorkflowStageDescriptor[]) {
  const byId = new Map(stages.map((stage) => [stage.id, stage]))
  const visited = new Set<string>()
  const ordered: WorkflowStageDescriptor[] = []

  function visit(stage: WorkflowStageDescriptor) {
    if (visited.has(stage.id)) return
    visited.add(stage.id)
    ordered.push(stage)
    for (const successorId of stage.successors) {
      const successor = byId.get(successorId)
      if (successor) visit(successor)
    }
  }

  for (const stage of stages.filter((item) => item.predecessors.length === 0)) visit(stage)
  for (const stage of stages) visit(stage)

  return ordered
}

function workflowFieldHelp(path: string): string {
  switch (path) {
    case 'workflow.runtime':
      return 'Selects the workflow runtime that executes this Agent flow. This should match a backend-supported orchestrator.'
    case 'workflow.template':
      return 'Selects the backend-owned workflow template. Use react_enterprise_qa_v3 (Controlled ReAct Loop) for new Agents. react_enterprise_qa_v2 is the single-pass baseline; enterprise_qa remains a compatibility path for older fixtures.'
    case 'workflow.checkpointer.provider':
      return 'Chooses where workflow state is checkpointed so multi-step runs can resume or inspect state consistently.'
    case 'workflow.checkpointer.uri':
      return 'Configures the checkpoint storage location used by the selected provider.'
    default:
      return 'Configures a workflow-level setting used by the Agent runtime.'
  }
}

function emptyStageConfig(stageId: string): WorkflowStageConfig {
  return {
    id: stageId,
    prompt: {
      business_context: '',
      task_instructions: [],
      output_preferences: [],
    },
    context: {},
  }
}

function normalizeStageConfig(stage: WorkflowStageConfig): WorkflowStageConfig {
  return {
    id: stage.id,
    prompt: {
      business_context: stage.prompt.business_context ?? '',
      task_instructions: stage.prompt.task_instructions ?? [],
      output_preferences: stage.prompt.output_preferences ?? [],
    },
    context: stage.context ?? {},
  }
}

function sanitizeStageConfigForDescriptor(
  stage: WorkflowStageConfig,
  descriptor: WorkflowTemplateDescriptor,
): WorkflowStageConfig {
  const stageDescriptor = descriptor.stages.find((candidate) => candidate.id === stage.id)
  if (!stageDescriptor?.editable_prompt_fields.length) {
    return {
      ...stage,
      prompt: emptyStageConfig(stage.id).prompt,
    }
  }
  return stage
}

function splitLines(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean)
}

function formatSuccessors(
  stage: WorkflowStageDescriptor,
  stageLabelById: Map<string, string>,
): string {
  if (stage.successors.length === 0) return 'Terminal'
  return stage.successors.map((stageId) => {
    const label = stageLabelById.get(stageId) ?? stageId
    const condition = stage.branch_conditions[stageId]
    return condition ? `${label} (${condition})` : label
  }).join(', ')
}

export type { WorkflowModuleEditorProps }
