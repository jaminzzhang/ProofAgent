import { useEffect, useMemo, useState } from 'react'
import type {
  WorkflowNodeConfig,
  WorkflowNodeContextPreview,
  WorkflowNodeDescriptor,
  WorkflowNodePromptConfig,
  WorkflowTemplateDescriptor,
} from '../../api/types'
import { CodeBlock } from '../CodeBlock'
import {
  readAgentYamlField,
  readWorkflowNodeConfigs,
  replaceWorkflowNodes,
} from '../../utils/agentYaml'
import { WORKFLOW_FIELDS } from './module-configs/workflow'

interface WorkflowModuleEditorProps {
  agentYaml: string
  descriptor: WorkflowTemplateDescriptor | null
  descriptorError?: string | null
  onFieldChange: (path: string[], value: string) => void
  onSaveCore: () => void
  onSaveNodes: (payload: {
    template_descriptor_version: string
    nodes: WorkflowNodeConfig[]
  }) => Promise<void>
  onPreviewNode: (
    nodeId: string,
    payload: {
      prompt: WorkflowNodePromptConfig
      context: Record<string, boolean>
    },
  ) => Promise<WorkflowNodeContextPreview>
  busy: boolean
  nodeBusy: boolean
}

export function WorkflowModuleEditor({
  agentYaml,
  descriptor,
  descriptorError,
  onFieldChange,
  onSaveCore,
  onSaveNodes,
  onPreviewNode,
  busy,
  nodeBusy,
}: WorkflowModuleEditorProps) {
  const [showYaml, setShowYaml] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [nodes, setNodes] = useState<WorkflowNodeConfig[]>([])
  const [preview, setPreview] = useState<WorkflowNodeContextPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)

  useEffect(() => {
    if (!descriptor) {
      setNodes([])
      setSelectedNodeId('')
      return
    }
    const configuredById = new Map(
      readWorkflowNodeConfigs(agentYaml).map((node) => [node.node_id, node]),
    )
    const nextNodes = descriptor.nodes.map((node) => {
      const configured = configuredById.get(node.node_id)
      return configured
        ? normalizeNodeConfig(configured)
        : emptyNodeConfig(node.node_id)
    })
    setNodes(nextNodes)
    setSelectedNodeId((current) => (
      current && descriptor.nodes.some((node) => node.node_id === current)
        ? current
        : descriptor.nodes[0]?.node_id ?? ''
    ))
  }, [agentYaml, descriptor])

  useEffect(() => {
    setPreview(null)
    setPreviewError(null)
  }, [selectedNodeId])

  const selectedDescriptor = descriptor?.nodes.find((node) => node.node_id === selectedNodeId) ?? null
  const selectedConfig = nodes.find((node) => node.node_id === selectedNodeId) ?? null
  const canEditPrompt = Boolean(selectedDescriptor?.editable_prompt_fields.length)
  const canConfigureContext = Boolean(selectedDescriptor?.context_options.length)
  const canPreviewSelected = canEditPrompt || canConfigureContext
  const localYaml = descriptor
    ? replaceWorkflowNodes(agentYaml, descriptor.descriptor_version, nodes)
    : agentYaml

  const nodeLabelById = useMemo(() => {
    const labels = new Map<string, string>()
    for (const node of descriptor?.nodes ?? []) labels.set(node.node_id, node.label)
    return labels
  }, [descriptor])

  function updateSelectedNode(updater: (node: WorkflowNodeConfig) => WorkflowNodeConfig) {
    if (!selectedConfig) return
    setNodes((current) => current.map((node) => (
      node.node_id === selectedConfig.node_id ? updater(node) : node
    )))
  }

  async function saveNodes() {
    if (!descriptor) return
    await onSaveNodes({
      template_descriptor_version: descriptor.descriptor_version,
      nodes: nodes.map((node) => sanitizeNodeConfigForDescriptor(node, descriptor)),
    })
  }

  async function previewSelectedNode() {
    if (!selectedConfig) return
    setPreviewBusy(true)
    setPreviewError(null)
    try {
      const result = await onPreviewNode(selectedConfig.node_id, {
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
            Workflow Configuration
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            {descriptor?.description ?? 'Backend-owned workflow descriptor'}
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
            {showYaml ? 'Hide YAML' : 'Show YAML'}
          </button>
          <button
            onClick={onSaveCore}
            disabled={busy}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {busy ? 'Saving...' : 'Save Core'}
          </button>
          <button
            onClick={saveNodes}
            disabled={nodeBusy || !descriptor || descriptor.name !== 'react_enterprise_qa'}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {nodeBusy ? 'Saving...' : 'Save Nodes'}
          </button>
        </div>
      </div>

      {showYaml && (
        <div className="border-b border-[var(--border)] p-5">
          <CodeBlock>{localYaml}</CodeBlock>
        </div>
      )}

      <div className="border-b border-[var(--border)] p-5">
        <div className="grid gap-4 md:grid-cols-3">
          {WORKFLOW_FIELDS.map((field) => (
            <label key={field.path.join('.')} className="block">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {field.label}
              </span>
              {field.input === 'select' && field.options ? (
                <select
                  value={readAgentYamlField(agentYaml, field.path)}
                  onChange={(event) => onFieldChange(field.path, event.target.value)}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                >
                  {field.options.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.input}
                  value={readAgentYamlField(agentYaml, field.path)}
                  onChange={(event) => onFieldChange(field.path, event.target.value)}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                />
              )}
            </label>
          ))}
        </div>
      </div>

      {descriptorError && (
        <div className="border-b border-[var(--border)] p-5 text-sm text-[var(--danger)]">
          {descriptorError}
        </div>
      )}

      <div className="grid gap-0 lg:grid-cols-[minmax(260px,0.9fr)_minmax(360px,1.1fr)]">
        <section className="border-b border-[var(--border)] p-5 lg:border-b-0 lg:border-r">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Relationship Map
              </h4>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                {descriptor?.descriptor_version ?? 'Descriptor not loaded'}
              </p>
            </div>
            {descriptor && (
              <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs text-[var(--text-secondary)]">
                {descriptor.nodes.length} nodes
              </span>
            )}
          </div>

          {!descriptor ? (
            <p className="text-sm text-[var(--text-muted)]">No workflow descriptor available.</p>
          ) : (
            <div className="space-y-3">
              {descriptor.nodes.map((node) => (
                <WorkflowMapNode
                  key={node.node_id}
                  node={node}
                  selected={node.node_id === selectedNodeId}
                  nodeLabelById={nodeLabelById}
                  onSelect={() => setSelectedNodeId(node.node_id)}
                />
              ))}
            </div>
          )}
        </section>

        <section className="p-5">
          {!selectedDescriptor || !selectedConfig ? (
            <p className="text-sm text-[var(--text-muted)]">Select a workflow node.</p>
          ) : (
            <div className="space-y-5">
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
                Harness-owned prompt is locked. Node Prompt is appended only as Business Context Addendum.
              </div>

              <label className="block">
                <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Business Context
                </span>
                <textarea
                  value={selectedConfig.prompt.business_context ?? ''}
                  disabled={!canEditPrompt}
                  onChange={(event) => updateSelectedNode((node) => ({
                    ...node,
                    prompt: { ...node.prompt, business_context: event.target.value },
                  }))}
                  rows={4}
                  className="w-full resize-y bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-60"
                />
              </label>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Task Instructions
                  </span>
                  <textarea
                    value={selectedConfig.prompt.task_instructions.join('\n')}
                    disabled={!canEditPrompt}
                    onChange={(event) => updateSelectedNode((node) => ({
                      ...node,
                      prompt: {
                        ...node.prompt,
                        task_instructions: splitLines(event.target.value),
                      },
                    }))}
                    rows={5}
                    className="w-full resize-y bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-60"
                  />
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Output Preferences
                  </span>
                  <textarea
                    value={selectedConfig.prompt.output_preferences.join('\n')}
                    disabled={!canEditPrompt}
                    onChange={(event) => updateSelectedNode((node) => ({
                      ...node,
                      prompt: {
                        ...node.prompt,
                        output_preferences: splitLines(event.target.value),
                      },
                    }))}
                    rows={5}
                    className="w-full resize-y bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-60"
                  />
                </label>
              </div>

              {selectedDescriptor.context_options.length > 0 && (
                <div>
                  <h5 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Context Options
                  </h5>
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
                          onChange={(event) => updateSelectedNode((node) => ({
                            ...node,
                            context: {
                              ...node.context,
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
                  onClick={previewSelectedNode}
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

function WorkflowMapNode({
  node,
  selected,
  nodeLabelById,
  onSelect,
}: {
  node: WorkflowNodeDescriptor
  selected: boolean
  nodeLabelById: Map<string, string>
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-md border p-3 text-left transition-colors ${
        selected
          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
          : 'border-[var(--border)] bg-[var(--bg-base)] hover:bg-[var(--bg-hover)]'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-[var(--text-primary)]">{node.label}</div>
          <div className="mt-1 font-mono text-xs text-[var(--text-muted)]">{node.node_id}</div>
        </div>
        <span className="rounded-full bg-[var(--bg-hover)] px-2 py-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
          {node.model_bearing ? 'model' : 'node'}
        </span>
      </div>
      <div className="mt-3 grid gap-2 text-xs text-[var(--text-muted)]">
        <div>
          <span className="font-semibold text-[var(--text-secondary)]">From: </span>
          {formatNodeList(node.predecessors, nodeLabelById, 'Start')}
        </div>
        <div>
          <span className="font-semibold text-[var(--text-secondary)]">Next: </span>
          {formatSuccessors(node, nodeLabelById)}
        </div>
      </div>
    </button>
  )
}

function emptyNodeConfig(nodeId: string): WorkflowNodeConfig {
  return {
    node_id: nodeId,
    prompt: {
      business_context: '',
      task_instructions: [],
      output_preferences: [],
    },
    context: {},
  }
}

function normalizeNodeConfig(node: WorkflowNodeConfig): WorkflowNodeConfig {
  return {
    node_id: node.node_id,
    prompt: {
      business_context: node.prompt.business_context ?? '',
      task_instructions: node.prompt.task_instructions ?? [],
      output_preferences: node.prompt.output_preferences ?? [],
    },
    context: node.context ?? {},
  }
}

function sanitizeNodeConfigForDescriptor(
  node: WorkflowNodeConfig,
  descriptor: WorkflowTemplateDescriptor,
): WorkflowNodeConfig {
  const nodeDescriptor = descriptor.nodes.find((candidate) => candidate.node_id === node.node_id)
  if (!nodeDescriptor?.editable_prompt_fields.length) {
    return {
      ...node,
      prompt: emptyNodeConfig(node.node_id).prompt,
    }
  }
  return node
}

function splitLines(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean)
}

function formatNodeList(
  nodeIds: string[],
  nodeLabelById: Map<string, string>,
  fallback: string,
): string {
  if (nodeIds.length === 0) return fallback
  return nodeIds.map((nodeId) => nodeLabelById.get(nodeId) ?? nodeId).join(', ')
}

function formatSuccessors(
  node: WorkflowNodeDescriptor,
  nodeLabelById: Map<string, string>,
): string {
  if (node.successors.length === 0) return 'Terminal'
  return node.successors.map((nodeId) => {
    const label = nodeLabelById.get(nodeId) ?? nodeId
    const condition = node.branch_conditions[nodeId]
    return condition ? `${label} (${condition})` : label
  }).join(', ')
}

export type { WorkflowModuleEditorProps }
