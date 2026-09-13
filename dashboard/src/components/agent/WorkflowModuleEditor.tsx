import { WorkflowConfigurationFlow } from './WorkflowConfigurationFlow'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, ConfigPanel, SectionField, Switch } from '@proofagent/ui'
import type {
  WorkflowStageConfig,
  WorkflowStageContextPreview,
  WorkflowStageDescriptor,
  WorkflowStagePromptConfig,
  WorkflowTemplateDescriptor,
  WorkflowPolicyPatch,
  ResolvedExecutionPlan,
} from '../../api/types'
import { WorkflowPolicyEditor } from './WorkflowPolicyEditor'
import { readWorkflowPolicies, workflowPolicyPatch } from './workflowPolicy'
import { CodeBlock } from '../CodeBlock'
import {
  readAgentYamlField,
  readWorkflowStageConfigs,
  replaceWorkflowStages,
} from '../../utils/agentYaml'
import { mergeStagePrompt, STRUCTURED_PROMPT_TEMPLATE } from './workflowPrompt'
import {
  canConfigurePrompt,
  CONTEXT_LABELS,
  stageDescription,
  stageName,
} from './workflowPresentation'

interface WorkflowModuleEditorProps {
  agentYaml: string
  descriptor: WorkflowTemplateDescriptor | null
  descriptorError?: string | null
  onSaveStages: (payload: {
    template: string
    template_descriptor_version: string
    stages: WorkflowStageConfig[]
    policy?: WorkflowPolicyPatch
  }) => Promise<void>
  revision?: number
  onPreviewExecution?: (policy: WorkflowPolicyPatch) => Promise<ResolvedExecutionPlan>
  onPreviewStage: (
    stageId: string,
    payload: {
      prompt: WorkflowStagePromptConfig
      context: Record<string, boolean>
    },
  ) => Promise<WorkflowStageContextPreview>
  onDirtyChange?: (dirty: boolean) => void
  busy: boolean
  stageBusy: boolean
}

export function WorkflowModuleEditor({
  agentYaml,
  descriptor,
  descriptorError,
  onSaveStages,
  onPreviewStage,
  onDirtyChange,
  revision,
  onPreviewExecution,
  busy,
  stageBusy,
}: WorkflowModuleEditorProps) {
  const initialPolicy = useMemo(() => readWorkflowPolicies(agentYaml), [agentYaml])
  const [policy, setPolicy] = useState(initialPolicy)
  const [policyInvalid, setPolicyInvalid] = useState(false)
  const policyChanges = workflowPolicyPatch(initialPolicy, policy)
  const policyDirty = Object.keys(policyChanges).length > 0
  const [executionPreview, setExecutionPreview] = useState<ResolvedExecutionPlan | null>(null)
  const [executionPreviewBusy, setExecutionPreviewBusy] = useState(false)
  const [executionPreviewError, setExecutionPreviewError] = useState<string | null>(null)
  const executionPreviewRevision = useRef(0)
  useEffect(() => { setPolicy(initialPolicy); setPolicyInvalid(false) }, [initialPolicy])
  useEffect(() => {
    executionPreviewRevision.current += 1
    setExecutionPreview(null)
    setExecutionPreviewBusy(false)
    setExecutionPreviewError(null)
    return () => { executionPreviewRevision.current += 1 }
  }, [policy, initialPolicy, revision, policyInvalid])
  const initialStages = useMemo(() => {
    if (!descriptor) return []
    const configured = readWorkflowStageConfigs(agentYaml)
    const byId = new Map(configured.map((stage) => [stage.id, stage]))
    return [
      ...descriptor.stages.map((stage) => {
        const saved = byId.get(stage.id)
        if (!saved) return emptyStage(stage.id)
        // Only consolidate the editable Prompt nodes. Hidden legacy settings stay intact.
        return canConfigurePrompt(stage)
          ? {
              ...saved,
              prompt: {
                business_context: mergeStagePrompt(saved.prompt),
                task_instructions: [],
                output_preferences: [],
              },
            }
          : {
              ...saved,
              prompt: {
                business_context: saved.prompt.business_context ?? '',
                task_instructions: saved.prompt.task_instructions,
                output_preferences: saved.prompt.output_preferences,
              },
            }
      }),
      ...configured
        .filter(
          (stage) => !descriptor.stages.some((item) => item.id === stage.id),
        )
        .map((stage) => ({
          ...stage,
          prompt: {
            ...stage.prompt,
            business_context: stage.prompt.business_context ?? '',
          },
        })),
    ] as WorkflowStageConfig[]
  }, [agentYaml, descriptor])
  const [stages, setStages] = useState(initialStages)
  const [selectedId, setSelectedId] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [technical, setTechnical] = useState(false)
  const [preview, setPreview] = useState<WorkflowStageContextPreview | null>(
    null,
  )
  const [previewBusy, setPreviewBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const previewRevision = useRef(0)
  const savingRef = useRef(false)
  const [flowExpanded, setFlowExpanded] = useState(false)
  const configurationRef = useRef<HTMLElement>(null)

  useEffect(() => {
    setStages(initialStages)
    setSelectedId((current) =>
      descriptor?.stages.some((stage) => stage.id === current)
        ? current
        : (descriptor?.stages.find(canConfigurePrompt)?.id ??
          descriptor?.stages[0]?.id ??
          ''),
    )
  }, [initialStages, descriptor])
  useEffect(() => {
    previewRevision.current += 1
    setPreview(null)
    setPreviewBusy(false)
    setError(null)
    setAdvanced(false)
    setTechnical(false)
  }, [selectedId, initialStages])

  const dirty =
    configurationFingerprint(stages) !== configurationFingerprint(initialStages) || policyDirty || policyInvalid
  useEffect(() => {
    onDirtyChange?.(dirty)
  }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const selected = descriptor?.stages.find((stage) => stage.id === selectedId)
  const config = stages.find((stage) => stage.id === selectedId)
  const editable = selected ? canConfigurePrompt(selected) : false
  const template = readAgentYamlField(agentYaml, ['workflow', 'template'])
  const version = readAgentYamlField(agentYaml, [
    'workflow',
    'template_descriptor_version',
  ])
  const compatible =
    !!descriptor &&
    template === descriptor.name &&
    (!version || version === descriptor.descriptor_version)
  const totalChars = stages.reduce(
    (sum, stage) =>
      sum +
      [...(stage.prompt.business_context ?? '')].length +
      stage.prompt.task_instructions.reduce(
        (n, text) => n + [...text].length,
        0,
      ) +
      stage.prompt.output_preferences.reduce(
        (n, text) => n + [...text].length,
        0,
      ),
    0,
  )
  const overBudget = totalChars > 12000
  const locked = busy || stageBusy || saving || !compatible || !!descriptorError
  const mismatch =
    descriptor && !compatible
      ? '配置与当前流程描述不一致，请刷新并核对版本后再保存。'
      : null
  const extraContext = config
    ? Object.entries(config.context).filter(([key]) => !(key in CONTEXT_LABELS))
    : []
  const availableContext =
    selected?.context_options.filter((key) => key in CONTEXT_LABELS) ?? []
  const localYaml = descriptor
    ? replaceWorkflowStages(
        agentYaml,
        version || descriptor.descriptor_version,
        stages,
      )
    : agentYaml

  function update(
    updater: (stage: WorkflowStageConfig) => WorkflowStageConfig,
  ) {
    if (locked || !config) return
    previewRevision.current += 1
    setPreview(null)
    setPreviewBusy(false)
    setError(null)
    setStages((current) =>
      current.map((stage) =>
        stage.id === selectedId ? updater(stage) : stage,
      ),
    )
  }
  async function save() {
    if (!descriptor || locked || !dirty || overBudget || policyInvalid || savingRef.current)
      return
    savingRef.current = true
    setSaving(true)
    setError(null)
    try {
      await onSaveStages({
        template,
        template_descriptor_version: version || descriptor.descriptor_version,
        stages,
        ...(policyDirty ? { policy: policyChanges } : {}),
      })
      // The caller supplies the persisted YAML. A failed API save never clears local edits.
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }
  async function previewExecution() {
    if (!onPreviewExecution || revision === undefined || locked || policyInvalid) return
    const request = ++executionPreviewRevision.current
    setExecutionPreviewBusy(true)
    setExecutionPreviewError(null)
    try {
      const result = await onPreviewExecution(policyChanges)
      if (request === executionPreviewRevision.current) setExecutionPreview(result)
    } catch (err) {
      if (request === executionPreviewRevision.current) setExecutionPreviewError(err instanceof Error ? err.message : String(err))
    } finally {
      if (request === executionPreviewRevision.current) setExecutionPreviewBusy(false)
    }
  }
  async function previewContext() {
    if (!config || !editable || locked) return
    const revision = ++previewRevision.current
    setPreviewBusy(true)
    setError(null)
    try {
      const result = await onPreviewStage(selectedId, {
        prompt: config.prompt,
        context: config.context,
      })
      if (previewRevision.current === revision) setPreview(result)
    } catch (err) {
      if (previewRevision.current === revision)
        setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (previewRevision.current === revision) setPreviewBusy(false)
    }
  }
  function nodeButton(stage: WorkflowStageDescriptor) {
    const current = stages.find((item) => item.id === stage.id)
    const initial = initialStages.find((item) => item.id === stage.id)
    const changed =
      configurationFingerprint(current ? [current] : []) !==
      configurationFingerprint(initial ? [initial] : [])
    return (
      <button
        key={stage.id}
        type="button"
        aria-label={stageName(stage)}
        aria-current={selectedId === stage.id ? 'true' : undefined}
        onClick={() => {
          setSelectedId(stage.id)
          if (flowExpanded)
            configurationRef.current?.focus({ preventScroll: true })
          setFlowExpanded(false)
        }}
        className={`w-full rounded-md border px-2 py-1.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${selectedId === stage.id ? 'border-[var(--accent)] bg-[var(--accent)]/10' : 'border-transparent hover:bg-[var(--bg-hover)]'}`}
      >
        <span className="flex items-center justify-between gap-2 text-xs font-medium text-[var(--text-primary)]">
          {stageName(stage)}
          {changed && (
            <span className="text-xs text-[var(--accent)]">未保存</span>
          )}
        </span>
      </button>
    )
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <ConfigPanel
        headingLevel={3}
        className="[&>header]:flex-col [&>header]:items-stretch sm:[&>header]:flex-row sm:[&>header]:items-center"
        title="Workflow"
        description="选择流程节点，编辑 Prompt。留空使用系统默认指令。"
        bodyPadding="flush"
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <span role="status" className="text-xs text-[var(--text-muted)]">
              {dirty ? '有未保存修改' : '没有未保存修改'}
            </span>
            <Button onClick={save} disabled={locked || !dirty || overBudget || policyInvalid}>
              {saving || stageBusy ? '保存中…' : '保存 Workflow'}
            </Button>
          </div>
        }
      >
        <WorkflowPolicyEditor
          value={policy} resetKey={agentYaml} descriptor={descriptor}
          onChange={setPolicy} onInvalidChange={setPolicyInvalid}
          onPreview={previewExecution} locked={locked}
          previewAvailable={!!onPreviewExecution && revision !== undefined}
          previewBusy={executionPreviewBusy} preview={executionPreview} previewError={executionPreviewError}
        />
        {(descriptorError || mismatch || error || overBudget) && (
          <div
            role="alert"
            className="m-4 rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] p-3 text-sm text-[var(--danger-fg)]"
          >
            {descriptorError ||
              mismatch ||
              error ||
              `Prompt 总长度为 ${totalChars} 字符，超过 12,000 字符限制，请精简后保存。`}
          </div>
        )}
        {!descriptor ? (
          <p className="p-5 text-sm text-[var(--text-muted)]">
            暂时无法加载流程配置，请刷新后重试。
          </p>
        ) : (
          <div className="grid lg:grid-cols-[224px_minmax(0,1fr)]">
            <aside className="min-w-0 border-b border-[var(--border)] lg:border-r lg:border-b-0">
              <button
                type="button"
                aria-expanded={flowExpanded}
                aria-controls="workflow-flow-navigation"
                onClick={() => setFlowExpanded(!flowExpanded)}
                className="flex w-full items-center justify-between gap-2 px-4 py-3 text-sm text-[var(--text-secondary)] lg:hidden"
              >
                <span>
                  {flowExpanded ? '收起流程' : '查看流程'} ·{' '}
                  {descriptor.stages.length} 个节点
                </span>
                <span className="text-xs">
                  {selected ? stageName(selected) : '选择节点'}{' '}
                  {flowExpanded ? '⌃' : '⌄'}
                </span>
              </button>
              <div
                id="workflow-flow-navigation"
                className={flowExpanded ? 'block' : 'hidden lg:block'}
              >
                <WorkflowConfigurationFlow
                  stages={descriptor.stages}
                  renderNode={nodeButton}
                />
              </div>
            </aside>
            <section
              ref={configurationRef}
              tabIndex={-1}
              aria-label="节点配置"
              className="min-w-0 space-y-4 p-4 sm:p-5"
            >
              {selected && config ? (
                <>
                  <div>
                    <h4 className="text-base font-semibold text-[var(--text-primary)]">
                      {stageName(selected)}
                    </h4>
                    <p className="mt-1 text-sm text-[var(--text-muted)]">
                      {stageDescription(selected)}
                    </p>
                  </div>
                  {editable ? (
                    <>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <label
                          htmlFor="stage-prompt"
                          className="text-sm font-medium text-[var(--text-primary)]"
                        >
                          Prompt
                        </label>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={locked}
                          onClick={() =>
                            update((stage) => ({
                              ...stage,
                              prompt: {
                                business_context: [
                                  stage.prompt.business_context,
                                  STRUCTURED_PROMPT_TEMPLATE,
                                ]
                                  .filter(Boolean)
                                  .join('\n\n'),
                                task_instructions: [],
                                output_preferences: [],
                              },
                            }))
                          }
                        >
                          插入结构模板
                        </Button>
                      </div>
                      <textarea
                        id="stage-prompt"
                        aria-describedby="prompt-help"
                        disabled={locked}
                        value={config.prompt.business_context ?? ''}
                        rows={12}
                        onChange={(event) =>
                          update((stage) => ({
                            ...stage,
                            prompt: {
                              business_context: event.target.value,
                              task_instructions: [],
                              output_preferences: [],
                            },
                          }))
                        }
                        placeholder="描述这个节点的业务背景、任务要求和输出偏好。"
                        className="w-full resize-y rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 py-3 text-sm leading-relaxed text-[var(--text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
                      />
                      <p
                        id="prompt-help"
                        className="text-xs text-[var(--text-muted)]"
                      >
                        模板只添加章节和填写提示，追加在现有内容之后。节点切换不会丢失修改。
                      </p>
                      <button
                        type="button"
                        aria-expanded={advanced}
                        onClick={() => setAdvanced(!advanced)}
                        className="rounded-md py-2 text-sm text-[var(--text-secondary)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                      >
                        高级设置
                      </button>
                      {advanced && (
                        <div className="space-y-4 rounded-md border border-[var(--border)] p-4">
                          <p className="text-xs text-[var(--text-muted)]">
                            仅在需要额外上下文时调整。这里不会启用知识、工具或改变权限。
                          </p>
                          {availableContext.map((option) => (
                            <SectionField
                              key={option}
                              label={CONTEXT_LABELS[option]}
                              inline
                            >
                              <Switch
                                aria-label={CONTEXT_LABELS[option]}
                                checked={!!config.context[option]}
                                disabled={locked}
                                onCheckedChange={(checked) =>
                                  update((stage) => ({
                                    ...stage,
                                    context: {
                                      ...stage.context,
                                      [option]: checked,
                                    },
                                  }))
                                }
                              />
                            </SectionField>
                          ))}
                          {extraContext.length > 0 && (
                            <p className="text-xs text-[var(--text-muted)]">
                              另有 {extraContext.length}{' '}
                              项原有上下文设置保留不变，可在技术信息中查看。
                            </p>
                          )}
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={previewContext}
                            disabled={previewBusy || locked}
                          >
                            {previewBusy ? '预览中…' : '预览节点上下文'}
                          </Button>
                          <p className="text-xs text-[var(--text-muted)]">
                            预览不调用模型；长文本可能被截断，请检查提示。
                          </p>
                          {preview && (
                            <div className="space-y-2">
                              <p className="text-xs font-medium">
                                实际 Prompt 补充内容
                              </p>
                              <CodeBlock>
                                {preview.business_context_addendum.text ||
                                  '未添加 Prompt。'}
                              </CodeBlock>
                              {!!preview.summary.truncation_applied && (
                                <p
                                  role="status"
                                  className="text-sm text-[var(--warning-fg)]"
                                >
                                  上下文超过运行长度限制，预览内容已截断。
                                </p>
                              )}
                              <CodeBlock>
                                {JSON.stringify(
                                  preview.structured_control_context,
                                  null,
                                  2,
                                )}
                              </CodeBlock>
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="rounded-md bg-[var(--bg-base)] p-4 text-sm text-[var(--text-secondary)]">
                      此节点由系统管理，无需日常配置。原有设置会保留。
                    </div>
                  )}
                  <div className="border-t border-[var(--border)] pt-3">
                    <button
                      type="button"
                      aria-expanded={technical}
                      onClick={() => setTechnical(!technical)}
                      className="rounded-md text-xs text-[var(--text-muted)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    >
                      技术信息
                    </button>
                    {technical && (
                      <div className="mt-3 space-y-3 text-xs text-[var(--text-secondary)]">
                        <p>
                          流程：{template} · 版本：
                          {version || descriptor.descriptor_version}
                        </p>
                        <p>节点 ID：{selected.id}</p>
                        <p>输入：{selected.input_summary}</p>
                        <p>输出：{selected.output_summary}</p>
                        <p>
                          后续节点：{selected.successors.join(', ') || '结束'}
                          。节点列表用于配置，不代表每次运行的固定顺序。
                        </p>
                        <CodeBlock>
                          {JSON.stringify(
                            {
                              branches: selected.branch_conditions,
                              context: config.context,
                              ...(!editable ? { prompt: config.prompt } : {}),
                            },
                            null,
                            2,
                          )}
                        </CodeBlock>
                        <p>当前 Workflow YAML（只读）</p>
                        <CodeBlock>{localYaml}</CodeBlock>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <p>请选择一个节点。</p>
              )}
            </section>
          </div>
        )}
      </ConfigPanel>
    </div>
  )
}
function configurationFingerprint(stages: WorkflowStageConfig[]): string {
  return JSON.stringify(
    stages.map((stage) => ({
      ...stage,
      context: Object.fromEntries(
        Object.entries(stage.context)
          .filter(([, enabled]) => enabled)
          .sort(([a], [b]) => a.localeCompare(b)),
      ),
    })),
  )
}
function emptyStage(id: string): WorkflowStageConfig {
  return {
    id,
    prompt: {
      business_context: '',
      task_instructions: [],
      output_preferences: [],
    },
    context: {},
  }
}
export type { WorkflowModuleEditorProps }
