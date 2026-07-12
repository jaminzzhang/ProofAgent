import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Badge,
  Button,
  ConfigPanel,
  FieldGrid,
  KeyValueList,
  SectionField,
  Switch,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@proofagent/ui'
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
import {
  WORKFLOW_FIELDS,
  WORKFLOW_TEMPLATE_FALLBACK,
  WORKFLOW_TEMPLATE_DESCRIPTOR_VERSIONS,
  WORKFLOW_TEMPLATE_RUNTIMES,
} from './module-configs/workflow'
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
  const workflowRuntime = readAgentYamlField(agentYaml, ['workflow', 'runtime']) || t('workflow.notConfigured')
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

  function updateWorkflowField(path: string[], value: string) {
    onFieldChange(path, value)
    if (path.join('.') !== 'workflow.template') return

    const descriptorVersion =
      catalogTemplates.find((entry) => entry.name === value)?.descriptor_version
      ?? WORKFLOW_TEMPLATE_DESCRIPTOR_VERSIONS[value]
    if (descriptorVersion) {
      onFieldChange(['workflow', 'template_descriptor_version'], descriptorVersion)
    }
    const runtime = WORKFLOW_TEMPLATE_RUNTIMES[value]
    if (runtime) {
      onFieldChange(['workflow', 'runtime'], runtime)
    }
  }

  async function saveStages() {
    if (!descriptor) return
    // The descriptor_version sent with stages must match the currently selected
    // Template (the value persisted by the core save), NOT the descriptor prop,
    // which can describe a previously-loaded template after the dropdown changes.
    // Resolve it in three layers so the persisted template always wins:
    //   1. Dynamic Workflow Template Catalog (authoritative, live).
    //   2. WORKFLOW_TEMPLATE_DESCRIPTOR_VERSIONS map (catalog failed to load).
    //   3. The loaded descriptor's version (last resort).
    const selectedTemplateName = workflowTemplate
    const catalogDescriptorVersion =
      catalogTemplates.find((entry) => entry.name === selectedTemplateName)
        ?.descriptor_version ?? null
    const descriptorVersion =
      catalogDescriptorVersion
      ?? WORKFLOW_TEMPLATE_DESCRIPTOR_VERSIONS[selectedTemplateName]
      ?? descriptor.descriptor_version
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
    <div className="mx-auto max-w-6xl space-y-5">
      {/*
        Panel 1 — Workflow Template (job: pick the template + core config).
        Footer holds Save Core so the save action lives where the field job
        is, not stranded at the top of a giant panel.
      */}
      <ConfigPanel
        headingLevel={3}
        title={t('workflow.template')}
        description={t('workflow.templatePanelDescription')}
        actions={
          <Button variant="outline" size="sm" onClick={onSaveCore} disabled={busy}>
            {busy ? t('agentDetail.saving') : t('workflow.saveCore')}
          </Button>
        }
      >
        <section aria-label={t('workflow.templateSummary')}>
          {/* Template summary — its own labeled region, kept separate from the
              config fields below so the summary stays independently queryable.
              Template NAME and descriptor VERSION are two distinct fields, so
              they are labeled explicitly instead of stacked unlabeled. */}
          <div className="mb-4">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              {t('workflow.template')}
            </span>
            <p translate="no" className="mt-1 break-all font-mono text-sm font-medium text-[var(--text-primary)]">
              {workflowTemplate}
            </p>
            {descriptor && (
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                <span className="font-medium">Descriptor version:</span>{' '}
                <span translate="no" className="font-mono">{descriptor.descriptor_version}</span>
              </p>
            )}
          </div>
          <KeyValueList
            variant="inline"
            items={[
              { label: 'Runtime', value: workflowRuntime, kind: 'text' },
              {
                label: t('workflow.stages'),
                value: t('workflow.stagesCount').replace('{count}', String(stageCount)),
                kind: 'number',
              },
              { label: t('workflow.modelBearing'), value: String(modelBearingStageCount), kind: 'number' },
              { label: t('workflow.editable'), value: String(editableStageCount), kind: 'number' },
            ]}
          />

          {descriptorError && (
            <div
              role="alert"
              className="mt-4 rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] px-3 py-2 text-sm text-[var(--danger-fg)]"
            >
              {descriptorError}
            </div>
          )}
        </section>

        {/* Core config fields */}
        <h4 className="mt-6 mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          {t('workflow.design')}
        </h4>
        <FieldGrid cols={4} gap="md">
          {WORKFLOW_FIELDS.map((field) => {
            // The Template selector uses the dynamic catalog (or its static
            // fallback) instead of a hardcoded field.options list.
            const fieldOptions =
              field.path.join('.') === 'workflow.template'
                ? templateOptions
                : field.options
            const fieldId = `workflow-field-${field.path.join('-')}`
            return (
              <div key={field.path.join('.')} className="flex min-w-0 flex-col">
                <FieldHeader
                  label={field.label}
                  help={workflowFieldHelp(field.path.join('.'))}
                  htmlFor={fieldId}
                />
                {field.input === 'select' && fieldOptions ? (
                  <NativeSelect
                    id={fieldId}
                    value={readAgentYamlField(agentYaml, field.path)}
                    onChange={(event) => updateWorkflowField(field.path, event.target.value)}
                  >
                    {fieldOptions.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </NativeSelect>
                ) : (
                  <input
                    id={fieldId}
                    type={field.input}
                    value={readAgentYamlField(agentYaml, field.path)}
                    onChange={(event) => updateWorkflowField(field.path, event.target.value)}
                    className="h-9 w-full rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  />
                )}
              </div>
            )
          })}
        </FieldGrid>
      </ConfigPanel>

      {/*
        Panel 2 — Stage Design (job: read the relationship map + edit one stage).
        Save Stages lives in the title row (actions) next to the panel identity.
      */}
      <ConfigPanel
        headingLevel={3}
        title="Stage Design"
        description="Browse the relationship map and edit a stage's bounded prompt and context."
        bodyPadding="flush"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={saveStages}
            disabled={stageBusy || !descriptor || !descriptor.name.startsWith('react_enterprise_qa')}
          >
            {stageBusy ? t('agentDetail.saving') : t('workflow.saveStages')}
          </Button>
        }
      >
        <div className="grid gap-0 lg:grid-cols-[300px_minmax(0,1fr)]">
          {/* Relationship map */}
          <section
            aria-label="Relationship Map"
            className="bg-[var(--bg-base)] p-4 lg:border-r lg:border-[var(--border)]"
          >
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Relationship Map
                </h4>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  {descriptor?.descriptor_version ?? 'Descriptor not loaded'}
                </p>
              </div>
              {descriptor && (
                <Badge variant="subtle" className="shrink-0">
                  {descriptor.stages.length} stages
                </Badge>
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
                      <span className="text-[11px] tabular-nums text-[var(--text-muted)]">
                        {group.stages.length}
                      </span>
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

          {/* Stage Inspector */}
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
                  <div className="min-w-0">
                    <h4 className="text-base font-semibold text-[var(--text-primary)]">
                      {selectedDescriptor.label}
                    </h4>
                    <p className="mt-1 break-words text-sm text-[var(--text-muted)]">
                      {selectedDescriptor.description}
                    </p>
                  </div>
                  <Badge
                    variant={selectedDescriptor.model_bearing ? 'subtle' : 'outline'}
                    className="shrink-0"
                  >
                    {selectedDescriptor.model_bearing ? 'Model-bearing' : 'Governed'}
                  </Badge>
                </div>

                <dl className="grid gap-3 text-xs text-[var(--text-muted)] sm:grid-cols-3">
                  <div className="min-w-0 rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                    <dt className="font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                      Stage ID
                    </dt>
                    <dd translate="no" className="mt-1 break-all font-mono text-[var(--text-primary)]">
                      {selectedDescriptor.id}
                    </dd>
                  </div>
                  <div className="min-w-0 rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                    <dt className="font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                      Availability
                    </dt>
                    <dd className="mt-1 text-[var(--text-primary)]">
                      {selectedDescriptor.required ? 'Required' : 'Optional'}
                    </dd>
                  </div>
                  <div className="min-w-0 rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
                    <dt className="font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                      Editable prompt fields
                    </dt>
                    <dd className="mt-2 flex flex-wrap gap-1.5 font-mono text-[var(--text-primary)]">
                      {selectedDescriptor.editable_prompt_fields.length > 0 ? (
                        selectedDescriptor.editable_prompt_fields.map((field) => (
                          <span
                            key={field}
                            translate="no"
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
                  <div className="min-w-0">
                    <span className="font-semibold text-[var(--text-secondary)]">Input</span>
                    <p className="mt-1 break-words">
                      {selectedDescriptor.input_summary || 'Governed runtime input.'}
                    </p>
                  </div>
                  <div className="min-w-0">
                    <span className="font-semibold text-[var(--text-secondary)]">Output</span>
                    <p className="mt-1 break-words">
                      {selectedDescriptor.output_summary || 'Governed runtime output.'}
                    </p>
                  </div>
                </div>

                <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3 text-xs text-[var(--text-secondary)]">
                  Harness-owned prompt is locked. Stage Prompt is appended only as Business Context Addendum.
                </div>

                {/* Bounded prompt fields — textareas (genuinely free-form) */}
                <div className="flex min-w-0 flex-col">
                  <FieldHeader
                    label="Business Context"
                    help="Adds domain-specific context to this stage without replacing the harness-owned control prompt. Use it for policy scope, business rules, and stage-specific operating context."
                    htmlFor="stage-business-context"
                  />
                  <textarea
                    id="stage-business-context"
                    value={selectedConfig.prompt.business_context ?? ''}
                    disabled={!canEditPrompt}
                    onChange={(event) => updateSelectedStage((stage) => ({
                      ...stage,
                      prompt: { ...stage.prompt, business_context: event.target.value },
                    }))}
                    rows={4}
                    className="w-full resize-y rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
                  />
                </div>

                <FieldGrid cols={2} gap="md">
                  <div className="flex min-w-0 flex-col">
                    <FieldHeader
                      label="Task Instructions"
                      help="Adds short, line-by-line instructions for how this stage should perform its task. Each non-empty line is saved as one instruction."
                      htmlFor="stage-task-instructions"
                    />
                    <textarea
                      id="stage-task-instructions"
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
                      className="w-full resize-y rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
                    />
                  </div>
                  <div className="flex min-w-0 flex-col">
                    <FieldHeader
                      label="Output Preferences"
                      help="Controls how this stage should shape its output, such as evidence style, formatting preferences, or response constraints. Each non-empty line is saved separately."
                      htmlFor="stage-output-preferences"
                    />
                    <textarea
                      id="stage-output-preferences"
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
                      className="w-full resize-y rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
                    />
                  </div>
                </FieldGrid>

                {/* Context Options — shared Switch (was raw checkbox) */}
                {selectedDescriptor.context_options.length > 0 && (
                  <div>
                    <FieldHeader
                      label="Context Options"
                      help="Toggles structured runtime context that the harness can safely provide to this stage, such as Agent purpose or prior outcome state."
                    />
                    <div className="mt-2">
                      <FieldGrid cols={2} gap="sm">
                        {selectedDescriptor.context_options.map((option) => (
                          <SectionField
                            key={option}
                            label={<span translate="no">{option}</span>}
                            inline
                          >
                            <Switch
                              aria-label={option}
                              checked={Boolean(selectedConfig.context[option])}
                              disabled={!canConfigureContext}
                              onCheckedChange={(checked) => updateSelectedStage((stage) => ({
                                ...stage,
                                context: { ...stage.context, [option]: checked },
                              }))}
                            />
                          </SectionField>
                        ))}
                      </FieldGrid>
                    </div>
                  </div>
                )}

                {/* Preview action */}
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={previewSelectedStage}
                    disabled={previewBusy || !canPreviewSelected}
                  >
                    {previewBusy ? 'Previewing…' : 'Preview Context'}
                  </Button>
                  {previewError && (
                    <span role="alert" className="text-sm text-[var(--danger-fg)]">
                      {previewError}
                    </span>
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
      </ConfigPanel>

      {/*
        Panel 3 — Advanced (disclosed). Raw YAML is a read-only artifact of the
        same draft contract; no save here (Save Core / Save Stages own persistence).
      */}
      <ConfigPanel
        headingLevel={3}
        title={t('workflow.advancedYaml')}
        description="Read-only projection of the current draft contract YAML."
        actions={
          <Button variant="ghost" size="sm" onClick={() => setShowYaml(!showYaml)}>
            {showYaml ? t('moduleEditor.hideYaml') : t('workflow.advancedYaml')}
          </Button>
        }
        variant="nested"
      >
        {showYaml ? (
          <CodeBlock>{localYaml}</CodeBlock>
        ) : (
          <p className="text-sm text-[var(--text-muted)]">
            Reveal the YAML projection with “{t('workflow.advancedYaml')}”.
          </p>
        )}
      </ConfigPanel>
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
      <Button
        type="button"
        variant="outline"
        aria-pressed={selected}
        onClick={onSelect}
        className={`h-auto w-full justify-start whitespace-normal rounded-md px-3 py-2 text-left font-normal ${
          selected
            ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--text-primary)]'
            : 'bg-[var(--bg-surface)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
        }`}
      >
        <div className="w-full">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-[var(--text-primary)]">{stage.label}</div>
              <div translate="no" className="mt-0.5 truncate font-mono text-[11px] text-[var(--text-muted)]">{stage.id}</div>
            </div>
            <Badge variant={selected ? 'subtle' : 'outline'} className="shrink-0 text-[10px] uppercase">
              {stage.model_bearing ? 'model' : 'stage'}
            </Badge>
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
        </div>
      </Button>
    </div>
  )
}

/**
 * FieldHeader — label + a "?" affordance that explains the field. The help is
 * rendered through the shared `Tooltip` primitive (Portal-based), replacing the
 * old hand-rolled `absolute role="note"` span that overlapped neighbouring
 * columns in the config grid.
 *
 * The "?" trigger is a sibling of the label text (NOT a child of the <label>),
 * so it does not pollute the field's accessible name. The <label> associates
 * to its control via `htmlFor`.
 */
function FieldHeader({
  label,
  help,
  htmlFor,
}: {
  label: string
  help: string
  htmlFor?: string
}) {
  return (
    <div className="mb-1.5 flex min-w-0 items-center gap-1.5">
      <label htmlFor={htmlFor} className="truncate text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </label>
      <TooltipProvider delayDuration={150}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={`Explain ${label}`}
              className="inline-flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded-full border border-[var(--border)] text-[10px] font-semibold text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            >
              ?
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-xs normal-case leading-5 tracking-normal text-[var(--text-secondary)]">
            {help}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
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
      return 'Selects the backend-owned workflow template. react_enterprise_qa_v3 is the only production workflow template.'
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

/**
 * NativeSelect — the shared select styling used across the refactored editors
 * (data-URI chevron, semantic border, focus-visible ring). Wraps a native
 * `<select>` so form value semantics stay identical.
 */
function NativeSelect({
  id,
  value,
  onChange,
  children,
  ...rest
}: {
  id?: string
  value: string
  onChange: (event: React.ChangeEvent<HTMLSelectElement>) => void
  children: ReactNode
} & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'value' | 'onChange' | 'id'>) {
  return (
    <select
      id={id}
      value={value}
      onChange={onChange}
      className="h-9 w-full appearance-none rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 pr-9 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23737373' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'right 0.625rem center',
      }}
      {...rest}
    >
      {children}
    </select>
  )
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
