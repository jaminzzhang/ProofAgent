import { useEffect, useMemo, useState } from 'react'
import {
  Badge,
  Button,
  ConfigPanel,
  FieldGrid,
  Input,
  KeyValueList,
  SectionField,
} from '@proofagent/ui'
import { extractAgentYamlSection, readAgentYamlField } from '../../utils/agentYaml'
import { KnowledgeSource } from '../../api/types'
import { DEFAULT_AGENTIC_RETRIEVAL_MAX_STEPS, KNOWLEDGE_FIELDS } from './module-configs/knowledge'
import { EmptyState } from '../EmptyState'
import { useLocale } from '../../i18n/locale'

/** Shared native select styling, used by the bind form. */
function NativeSelect({
  id,
  value,
  onChange,
  children,
}: {
  id?: string
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
}) {
  return (
    <select
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-9 w-full appearance-none rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 pr-9 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23737373' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'right 0.625rem center',
      }}
    >
      {children}
    </select>
  )
}

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
  const { t } = useLocale()
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

  function handleRetrievalFieldChange(path: string[], value: string) {
    onFieldChange(path, value)
    if (
      path.join('.') === 'retrieval.strategy'
      && value === 'agentic'
      && !readAgentYamlField(agentYaml, ['retrieval', 'max_steps'])
    ) {
      onFieldChange(['retrieval', 'max_steps'], DEFAULT_AGENTIC_RETRIEVAL_MAX_STEPS)
    }
  }

  return (
    <div className="space-y-6">
      {/* SECTION 1: Active Bound Sources */}
      <ConfigPanel
        headingLevel={3}
        title={t('knowledgeEditor.activeSources')}
        description={t('knowledgeEditor.activeSourcesDescription')}
      >
        {parsedBindings.length === 0 ? (
          <EmptyState message={t('knowledgeEditor.noBoundSources')} />
        ) : (
          <FieldGrid cols={2} gap="md">
            {parsedBindings.map((binding, idx) => {
              const sourceInfo = knowledgeSources.find(
                (s) => s.source_id === binding.source_id,
              )
              return (
                <div
                  key={`${binding.source_id}-${idx}`}
                  className="flex min-w-0 flex-col justify-between rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4 transition-colors hover:border-[var(--accent)]"
                >
                  <div className="min-w-0">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate font-semibold text-[var(--text-primary)]">
                        {sourceInfo ? sourceInfo.name : t('knowledgeEditor.unknownSource')}
                      </span>
                      {binding.failure_mode === 'required' ? (
                        <Badge variant="danger" className="shrink-0 text-[10px] uppercase">
                          {t('knowledgeEditor.required')}
                        </Badge>
                      ) : (
                        <Badge variant="neutral" className="shrink-0 text-[10px] uppercase">
                          {t('knowledgeEditor.advisory')}
                        </Badge>
                      )}
                    </div>
                    <div
                      translate="no"
                      className="mb-3 break-all font-mono text-xs text-[var(--text-muted)]"
                    >
                      {binding.source_id}
                    </div>
                  </div>

                  <div className="flex min-w-0 items-end justify-between gap-3 border-t border-[var(--border)] pt-3">
                    <KeyValueList
                      variant="inline"
                      className="min-w-0 flex-1"
                      items={[
                        {
                          label: t('knowledgeEditor.alias'),
                          value: binding.alias || '—',
                          kind: 'text',
                        },
                        {
                          label: t('knowledgeEditor.weight'),
                          value: binding.fusion_weight,
                          kind: 'number',
                        },
                      ]}
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onUnbindSource(binding.binding_id)}
                      disabled={busy}
                      className="shrink-0 text-[var(--danger-fg)] hover:bg-[var(--danger-bg)]"
                    >
                      {t('knowledgeEditor.remove')}
                    </Button>
                  </div>
                </div>
              )
            })}
          </FieldGrid>
        )}
      </ConfigPanel>

      {/* SECTION 2: Bind New Source Form */}
      <ConfigPanel
        headingLevel={3}
        title={t('knowledgeEditor.bindNewSource')}
        description={t('knowledgeEditor.bindDescription')}
        actions={
          <Badge variant="subtle">
            {t('knowledgeEditor.publishedAvailable').replace(
              '{count}',
              String(publishedSources.length),
            )}
          </Badge>
        }
      >
        {unavailableCount > 0 && (
          <p className="-mt-2 mb-4 text-xs text-[var(--text-muted)]">
            {t('knowledgeEditor.unavailableHidden').replace(
              '{count}',
              String(unavailableCount),
            )}
          </p>
        )}

        {knowledgeSourceError && (
          <div
            role="alert"
            className="mb-4 rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] px-3 py-2 text-sm text-[var(--danger-fg)]"
          >
            {knowledgeSourceError}
          </div>
        )}

        {publishedSources.length === 0 ? (
          <EmptyState message={t('knowledgeEditor.noPublished')} />
        ) : (
          <FieldGrid cols={2} gap="md">
            <SectionField
              htmlFor="knowledge-bind-source"
              label={t('knowledgeEditor.knowledgeSource')}
            >
              <NativeSelect
                id="knowledge-bind-source"
                value={selectedSourceId}
                onChange={(value) => setSelectedSourceId(value)}
              >
                {publishedSources.map((source) => (
                  <option key={source.source_id} value={source.source_id}>
                    {source.name} ({source.provider})
                  </option>
                ))}
              </NativeSelect>
            </SectionField>

            <SectionField
              htmlFor="knowledge-bind-alias"
              label={t('knowledgeEditor.aliasLabel')}
            >
              <Input
                id="knowledge-bind-alias"
                value={bindingAlias}
                onChange={(e) => setBindingAlias(e.target.value)}
                placeholder={t('knowledgeEditor.aliasPlaceholder')}
              />
            </SectionField>

            <SectionField
              htmlFor="knowledge-bind-failure-mode"
              label={t('knowledgeEditor.failureMode')}
              description="Required sources block the answer if unavailable; advisory sources degrade gracefully."
            >
              <NativeSelect
                id="knowledge-bind-failure-mode"
                value={bindingFailureMode}
                onChange={(value) =>
                  setBindingFailureMode(value as 'required' | 'advisory')
                }
              >
                <option value="required">required</option>
                <option value="advisory">advisory</option>
              </NativeSelect>
            </SectionField>

            <SectionField
              htmlFor="knowledge-bind-fusion-weight"
              label={t('knowledgeEditor.fusionWeight')}
            >
              <Input
                id="knowledge-bind-fusion-weight"
                type="number"
                min="0.1"
                step="0.1"
                value={bindingFusionWeight}
                onChange={(e) => setBindingFusionWeight(e.target.value)}
              />
            </SectionField>

            <SectionField
              htmlFor="knowledge-bind-top-k"
              label={t('knowledgeEditor.topKOverride')}
            >
              <Input
                id="knowledge-bind-top-k"
                type="number"
                min="1"
                value={bindingTopK}
                onChange={(e) => setBindingTopK(e.target.value)}
                placeholder={t('knowledgeEditor.topKPlaceholder')}
              />
            </SectionField>

            <div className="flex items-end justify-end">
              <Button
                onClick={handleBind}
                disabled={busy || publishedSources.length === 0}
              >
                {busy ? t('knowledgeEditor.binding') : t('knowledgeEditor.bindSource')}
              </Button>
            </div>
          </FieldGrid>
        )}
      </ConfigPanel>

      {/* SECTION 3: Global Retrieval Settings */}
      <ConfigPanel
        headingLevel={3}
        title={t('knowledgeEditor.globalRetrieval')}
        description={t('knowledgeEditor.globalRetrievalDescription')}
        footer={
          <div className="flex justify-end">
            <Button variant="outline" size="sm" onClick={onSave} disabled={busy}>
              {busy ? t('agentDetail.saving') : t('knowledgeEditor.saveKnowledge')}
            </Button>
          </div>
        }
      >
        <FieldGrid cols={4} gap="md">
          {KNOWLEDGE_FIELDS.map((field) => {
            const currentValue = readAgentYamlField(agentYaml, field.path)
            const fieldId = `knowledge-field-${field.path.join('-')}`
            return (
              <SectionField
                key={field.path.join('.')}
                htmlFor={fieldId}
                label={field.label}
                description={field.description}
              >
                {field.input === 'select' && field.options ? (
                  <NativeSelect
                    id={fieldId}
                    value={currentValue}
                    onChange={(value) => handleRetrievalFieldChange(field.path, value)}
                  >
                    {field.options.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </NativeSelect>
                ) : (
                  <Input
                    id={fieldId}
                    type={field.input === 'number' ? 'number' : 'text'}
                    value={currentValue}
                    onChange={(e) =>
                      handleRetrievalFieldChange(field.path, e.target.value)
                    }
                  />
                )}
              </SectionField>
            )
          })}
        </FieldGrid>
      </ConfigPanel>
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
