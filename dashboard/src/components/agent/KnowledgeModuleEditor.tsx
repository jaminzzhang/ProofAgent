import React, { useEffect, useMemo, useState } from 'react'
import { extractAgentYamlSection, readAgentYamlField } from '../../utils/agentYaml'
import { KnowledgeSource } from '../../api/types'
import { KNOWLEDGE_FIELDS } from './module-configs/knowledge'
import { EmptyState } from '../EmptyState'

interface KnowledgeModuleEditorProps {
  agentYaml: string
  knowledgeSources: KnowledgeSource[]
  onFieldChange: (path: string[], value: string) => void
  onSave: () => void
  onBindSource: (payload: {
    source_id: string
    alias: string
    failure_mode: 'required' | 'advisory'
    fusion_weight: number
    top_k?: number
  }) => Promise<void>
  onUnbindSource: (bindingId: string) => Promise<void>
  busy: boolean
  knowledgeSourceError: string | null
}

export function KnowledgeModuleEditor({
  agentYaml,
  knowledgeSources,
  onFieldChange,
  onSave,
  onBindSource,
  onUnbindSource,
  busy,
  knowledgeSourceError,
}: KnowledgeModuleEditorProps) {
  const publishedSources = useMemo(
    () => knowledgeSources.filter((source) => (
      source.lifecycle_state === 'ACTIVE' && Boolean(source.published_snapshot_id)
    )),
    [knowledgeSources],
  )
  const unavailableCount = knowledgeSources.length - publishedSources.length
  // Bind form state
  const [selectedSourceId, setSelectedSourceId] = useState<string>('')
  const [bindingAlias, setBindingAlias] = useState('')
  const [bindingFailureMode, setBindingFailureMode] = useState<'required' | 'advisory'>('required')
  const [bindingFusionWeight, setBindingFusionWeight] = useState('1.0')
  const [bindingTopK, setBindingTopK] = useState('')

  useEffect(() => {
    if (publishedSources.length === 0) {
      setSelectedSourceId('')
      return
    }
    if (!publishedSources.some((source) => source.source_id === selectedSourceId)) {
      setSelectedSourceId(publishedSources[0].source_id)
    }
  }, [publishedSources, selectedSourceId])

  const parsedBindings = parseKnowledgeBindings(agentYaml)

  async function handleBind() {
    const sourceId = selectedSourceId || publishedSources[0]?.source_id
    if (!sourceId) return

    const payload: Parameters<typeof onBindSource>[0] = {
      source_id: sourceId,
      alias: bindingAlias,
      failure_mode: bindingFailureMode,
      fusion_weight: Number(bindingFusionWeight) || 1,
    }

    const topK = Number(bindingTopK)
    if (bindingTopK.trim() && Number.isFinite(topK) && topK > 0) {
      payload.top_k = topK
    }

    await onBindSource(payload)
    
    // Reset form after bind
    setBindingAlias('')
    setBindingTopK('')
    setBindingFailureMode('required')
    setBindingFusionWeight('1.0')
  }

  return (
    <div className="space-y-6">
      {/* SECTION 1: Active Bound Sources */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Active Bound Sources
        </h3>
        <p className="mt-1 text-sm text-[var(--text-muted)] mb-4">
          These knowledge sources are currently bound to this Agent draft.
        </p>

        {parsedBindings.length === 0 ? (
          <EmptyState message="No sources bound to this Agent yet." />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {parsedBindings.map((binding, idx) => {
              const sourceInfo = knowledgeSources.find(s => s.source_id === binding.source_id)
              return (
                <div key={`${binding.source_id}-${idx}`} className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4 flex flex-col justify-between transition-colors hover:border-[var(--accent)]">
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-semibold text-[var(--text-primary)]">
                        {sourceInfo ? sourceInfo.name : 'Unknown Source'}
                      </span>
                      {binding.failure_mode === 'required' ? (
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[var(--danger)]/10 text-[var(--danger)]">Required</span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[var(--accent)]/10 text-[var(--accent)]">Advisory</span>
                      )}
                    </div>
                    <div className="text-xs font-mono text-[var(--text-muted)] mb-3">
                      {binding.source_id}
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-3 text-xs text-[var(--text-secondary)]">
                    <div className="flex items-center gap-1">
                      <span className="font-semibold text-[var(--text-muted)]">Alias:</span>
                      <span>{binding.alias || '-'}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="font-semibold text-[var(--text-muted)]">Weight:</span>
                      <span>{binding.fusion_weight}</span>
                    </div>
                    <div className="ml-auto">
                      <button
                        onClick={() => onUnbindSource(binding.binding_id)}
                        disabled={busy}
                        className="text-[var(--danger)] hover:text-red-500 font-medium disabled:opacity-50 transition-colors"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* SECTION 2: Bind New Source Form */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              Bind New Source
            </h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              Attach a shared Knowledge Source to this Agent.
            </p>
          </div>
          <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)]">
            {publishedSources.length} published available
          </span>
        </div>
        {unavailableCount > 0 && (
          <p className="mb-4 text-xs text-[var(--text-muted)]">
            {unavailableCount} unavailable Source{unavailableCount === 1 ? '' : 's'} hidden until active and published.
          </p>
        )}

        {knowledgeSourceError && (
          <div className="mb-4 rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
            {knowledgeSourceError}
          </div>
        )}

        {publishedSources.length === 0 ? (
          <EmptyState message="No published shared Knowledge Sources are available. Publish one in Knowledge Hub first." />
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                Knowledge Source
              </label>
              <select
                value={selectedSourceId}
                onChange={(event) => setSelectedSourceId(event.target.value)}
                className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              >
                {publishedSources.map((source) => (
                  <option key={source.source_id} value={source.source_id}>
                    {source.name} ({source.provider})
                  </option>
                ))}
              </select>
            </div>
            
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

            <div className="grid gap-4 grid-cols-2">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                  Failure Mode
                </label>
                <select
                  value={bindingFailureMode}
                  onChange={(event) => setBindingFailureMode(event.target.value as 'required' | 'advisory')}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value="required">required</option>
                  <option value="advisory">advisory</option>
                </select>
              </div>
              
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

            <div className="lg:col-span-2 flex justify-end mt-2">
              <button
                onClick={handleBind}
                disabled={busy || publishedSources.length === 0}
                className="rounded-md bg-[var(--accent)] px-6 py-2 text-sm font-medium text-[var(--accent-fg)] hover:opacity-80 disabled:opacity-50 transition-all"
              >
                {busy ? 'Binding...' : 'Bind Source'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* SECTION 3: Global Retrieval Settings */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Global Retrieval Settings
        </h3>
        <p className="mt-1 text-sm text-[var(--text-muted)] mb-4">
          Agent-level retrieval controls that apply across all bound knowledge sources.
        </p>

        <div className="grid gap-6 md:grid-cols-3">
          {KNOWLEDGE_FIELDS.map((field) => {
            const currentValue = readAgentYamlField(agentYaml, field.path)
            return (
              <div key={field.path.join('.')}>
                <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                  {field.label}
                </label>
                {field.input === 'select' && field.options ? (
                  <select
                    value={currentValue}
                    onChange={(e) => onFieldChange(field.path, e.target.value)}
                    className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  >
                    {field.options.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.input === 'number' ? 'number' : 'text'}
                    value={currentValue}
                    onChange={(e) => onFieldChange(field.path, e.target.value)}
                    className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  />
                )}
                {field.description && (
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">{field.description}</p>
                )}
              </div>
            )
          })}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onSave}
            disabled={busy}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50 transition-colors"
          >
            {busy ? 'Saving...' : 'Save Workflow'}
          </button>
        </div>
      </div>
    </div>
  )
}

interface ParsedKnowledgeBinding {
  binding_id: string
  source_id: string
  alias: string
  failure_mode: string
  fusion_weight: string
}

function parseKnowledgeBindings(agentYaml: string): ParsedKnowledgeBinding[] {
  const bindingsYaml = extractAgentYamlSection(agentYaml, 'knowledge_bindings') || ''
  return bindingsYaml
    .split(/\n\s*-\s*binding_id:/)
    .slice(1)
    .map((block) => {
      const bindingIdMatch = block.match(/^\s*([^\s\n]+)/)
      const sourceRefMatch = block.match(/source_ref:\s*\n(?:\s+[^\n]*\n)*?\s+source_id:\s*([^\s\n]+)/)
      const aliasMatch = block.match(/alias:\s*([^\s\n]+)/)
      const failureModeMatch = block.match(/failure_mode:\s*([^\s\n]+)/)
      const weightMatch = block.match(/fusion_weight:\s*([^\s\n]+)/)
      if (!bindingIdMatch || !sourceRefMatch) return null
      return {
        binding_id: unquoteYamlScalar(bindingIdMatch[1]),
        source_id: unquoteYamlScalar(sourceRefMatch[1]),
        alias: aliasMatch ? unquoteYamlScalar(aliasMatch[1]) : '',
        failure_mode: failureModeMatch ? unquoteYamlScalar(failureModeMatch[1]) : 'required',
        fusion_weight: weightMatch ? unquoteYamlScalar(weightMatch[1]) : '1.0',
      }
    })
    .filter((binding): binding is ParsedKnowledgeBinding => Boolean(binding))
}

function unquoteYamlScalar(value: string): string {
  return value.replace(/['"]/g, '')
}
