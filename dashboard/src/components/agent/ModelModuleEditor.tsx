import { useState } from 'react'
import type { ReactNode } from 'react'
import type { AgentYamlMapping } from '../../utils/agentYaml'
import {
  Badge,
  Button,
  ConfigPanel,
  FieldGrid,
  Input,
  SectionField,
  Switch,
  cn,
} from '@proofagent/ui'
import { CodeBlock } from '../CodeBlock'
import type { SharedModelConnection } from '../../api/types'
import { extractAgentYamlSection, readAgentYamlField } from '../../utils/agentYaml'
import { useLocale } from '../../i18n/locale'

const MODEL_PROVIDER_OPTIONS = [
  'deterministic',
  'openai_compatible',
  'openai',
  'deepseek',
  'azure_openai',
  'anthropic',
]
// Common model names per provider, surfaced as combobox suggestions. The field
// stays editable so custom/finetuned names can still be typed.
const MODEL_NAME_SUGGESTIONS: Record<string, string[]> = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'o1', 'o3-mini'],
  azure_openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1'],
  anthropic: [
    'claude-3-5-sonnet-latest',
    'claude-3-5-haiku-latest',
    'claude-sonnet-4-20250514',
  ],
  deepseek: ['deepseek-chat', 'deepseek-reasoner'],
  openai_compatible: ['deepseek-chat', 'qwen2.5-72b-instruct'],
  deterministic: ['echo'],
}
const DEFAULT_TEMPERATURE = '0'
const DEFAULT_MAX_OUTPUT_TOKENS = '800'
const DEFAULT_TIMEOUT_SECONDS = '20'
const DEFAULT_DEEPSEEK_ENDPOINT_MODE = 'beta'

interface ModelModuleEditorProps {
  agentYaml: string
  modelConnections?: readonly SharedModelConnection[]
  onFieldChange: (path: string[], value: string) => void
  onModelConfigChange?: (path: string[], value: AgentYamlMapping) => void
  onCreateSharedModelConnection?: (payload: {
    display_name: string
    provider: string
    model_identifier: string
    base_url?: string | null
    credential_ref: { type: 'env'; name: string }
    timeout_seconds?: number | null
  }) => Promise<SharedModelConnection>
  onSave: () => void
  busy: boolean
}

interface ModelRole {
  title: string
  sourceLabel: string
  basePath: string[]
  subtitle?: string
  reviewer?: boolean
}

const ANSWER_ROLE: ModelRole = {
  title: 'Answer Model',
  sourceLabel: 'Answer Model Source',
  basePath: ['model'],
  subtitle: 'Final answer generation model',
}

const PLANNER_ROLE: ModelRole = {
  title: 'Planner Model',
  sourceLabel: 'Planner Model Source',
  basePath: ['react', 'planner'],
  subtitle: 'ReAct reasoning and tool planning model',
}

const REVIEWER_ROLE: ModelRole = {
  title: 'Reviewer Model',
  sourceLabel: 'Reviewer Model Source',
  basePath: ['review', 'subagent'],
  subtitle: 'Harness review subagent model',
  reviewer: true,
}

export function ModelModuleEditor({
  agentYaml,
  modelConnections = [],
  onFieldChange,
  onModelConfigChange,
  onCreateSharedModelConnection,
  onSave,
  busy,
}: ModelModuleEditorProps) {
  const { t } = useLocale()
  const [strategy, setStrategy] = useState<'unified' | 'role-specific'>('unified')
  const [showYaml, setShowYaml] = useState(false)
  const [localStatus, setLocalStatus] = useState<string | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [creatingShared, setCreatingShared] = useState<string | null>(null)

  const sectionYaml = [
    extractAgentYamlSection(agentYaml, 'model'),
    extractAgentYamlSection(agentYaml, 'react'),
    extractAgentYamlSection(agentYaml, 'review'),
  ]
    .filter(Boolean)
    .join('\n')

  function applyModelConfig(path: string[], value: AgentYamlMapping) {
    onModelConfigChange?.(path, value)
  }

  function handleSourceChange(role: ModelRole, value: string) {
    applyModelConfig(role.basePath, modelConfigForSource(agentYaml, role, value))
  }

  function handleUnifiedSourceChange(value: string) {
    for (const role of [ANSWER_ROLE, PLANNER_ROLE, REVIEWER_ROLE]) {
      applyModelConfig(role.basePath, modelConfigForSource(agentYaml, role, value))
    }
  }

  function handleUnifiedFieldChange(subPath: string[], value: string) {
    onFieldChange(['model', ...subPath], value)
    onFieldChange(['react', 'planner', ...subPath], value)
    onFieldChange(['review', 'subagent', ...subPath], value)
  }

  async function handleSaveAsShared(role: ModelRole) {
    if (!onCreateSharedModelConnection) return
    setCreatingShared(role.title)
    setLocalStatus(null)
    setLocalError(null)
    try {
      const connection = await onCreateSharedModelConnection(
        sharedConnectionPayload(agentYaml, role),
      )
      setLocalStatus(`Created shared model connection ${connection.connection_id}.`)
      if (window.confirm('Switch this role to the new Shared Model Connection?')) {
        applyModelConfig(
          role.basePath,
          modelConfigForSource(agentYaml, role, `shared:${connection.connection_id}`),
        )
      }
    } catch (err) {
      setLocalError(
        err instanceof Error ? err.message : 'Unable to create shared model connection.',
      )
    } finally {
      setCreatingShared(null)
    }
  }

  const recordReasoningPath = ['react', 'record_reasoning_summary']
  const recordReasoning =
    readAgentYamlField(agentYaml, recordReasoningPath) !== 'false'

  return (
    <ConfigPanel
      headingLevel={3}
      title={t('model.configuration')}
      description={t('model.description')}
      actions={
        <>
          {/* Segmented control: Unified vs Role-specific */}
          <div
            role="group"
            aria-label="Model configuration strategy"
            className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-0.5"
          >
            {(['unified', 'role-specific'] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={strategy === value}
                onClick={() => setStrategy(value)}
                className={cn(
                  'rounded-sm px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]',
                  strategy === value
                    ? 'bg-[var(--accent)]/10 text-[var(--accent)] shadow-sm'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]',
                )}
              >
                {value === 'unified'
                  ? t('model.unifiedSetup')
                  : t('model.roleSpecific')}
              </button>
            ))}
          </div>
          <Button variant="ghost" size="sm" onClick={() => setShowYaml(!showYaml)}>
            {showYaml ? t('moduleEditor.hideYaml') : t('moduleEditor.showYaml')}
          </Button>
          <Button variant="default" size="sm" onClick={onSave} disabled={busy}>
            {busy ? t('agentDetail.saving') : t('model.saveConfig')}
          </Button>
        </>
      }
      footer={
        showYaml && sectionYaml ? (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              model / react / review .yaml
            </h4>
            <CodeBlock>{sectionYaml}</CodeBlock>
          </div>
        ) : undefined
      }
    >
      <div className="space-y-6">
        {strategy === 'unified' ? (
          <ModelRoleCard
            role={{
              title: 'Primary Model Settings',
              sourceLabel: 'Primary Model Source',
              basePath: ['model'],
              subtitle: 'These settings apply to Answer, Planner, and Reviewer roles.',
            }}
            agentYaml={agentYaml}
            modelConnections={modelConnections}
            unified
            onSourceChange={handleUnifiedSourceChange}
            onFieldChange={handleUnifiedFieldChange}
            onSaveAsShared={() =>
              handleSaveAsShared({
                title: 'Primary Model Settings',
                sourceLabel: 'Primary Model Source',
                basePath: ['model'],
              })
            }
            creatingShared={creatingShared === 'Primary Model Settings'}
          />
        ) : (
          <div className="space-y-6">
            <ModelRoleCard
              role={ANSWER_ROLE}
              agentYaml={agentYaml}
              modelConnections={modelConnections}
              onSourceChange={(value) => handleSourceChange(ANSWER_ROLE, value)}
              onFieldChange={(path, value) => onFieldChange(path, value)}
              onSaveAsShared={() => handleSaveAsShared(ANSWER_ROLE)}
              creatingShared={creatingShared === ANSWER_ROLE.title}
            />
            <ModelRoleCard
              role={PLANNER_ROLE}
              agentYaml={agentYaml}
              modelConnections={modelConnections}
              onSourceChange={(value) => handleSourceChange(PLANNER_ROLE, value)}
              onFieldChange={(path, value) => onFieldChange(path, value)}
              onSaveAsShared={() => handleSaveAsShared(PLANNER_ROLE)}
              creatingShared={creatingShared === PLANNER_ROLE.title}
            />
            <ModelRoleCard
              role={REVIEWER_ROLE}
              agentYaml={agentYaml}
              modelConnections={modelConnections}
              onSourceChange={(value) => handleSourceChange(REVIEWER_ROLE, value)}
              onFieldChange={(path, value) => onFieldChange(path, value)}
              onSaveAsShared={() => handleSaveAsShared(REVIEWER_ROLE)}
              creatingShared={creatingShared === REVIEWER_ROLE.title}
              extraFields={
                <FieldGrid cols={2} gap="md" className="mb-4">
                  <SectionField
                    label="Review Mode"
                    htmlFor="review-mode"
                    description="Rules-only enforces deterministic checks; Auto also reasons with the reviewer model."
                  >
                    <NativeSelect
                      id="review-mode"
                      value={readAgentYamlField(agentYaml, ['review', 'mode']) || 'rules_only'}
                      onChange={(value) => onFieldChange(['review', 'mode'], value)}
                      options={[
                        { value: 'rules_only', label: 'Rules Only' },
                        { value: 'auto', label: 'Auto' },
                      ]}
                    />
                  </SectionField>
                  <SectionField
                    label="Fail Closed"
                    htmlFor="review-fail-closed"
                    description="When on, a reviewer error blocks the answer rather than passing it through."
                    inline
                  >
                    <Switch
                      id="review-fail-closed"
                      checked={
                        readAgentYamlField(agentYaml, [
                          'review',
                          'subagent',
                          'fail_closed',
                        ]) !== 'false'
                      }
                      onCheckedChange={(checked) =>
                        onFieldChange(
                          ['review', 'subagent', 'fail_closed'],
                          checked ? 'true' : 'false',
                        )
                      }
                    />
                  </SectionField>
                </FieldGrid>
              }
            />
          </div>
        )}

        {localStatus && (
          <div
            role="status"
            className="rounded-md border border-[var(--success-border)] bg-[var(--success-bg)] px-4 py-3 text-sm text-[var(--success-fg)]"
          >
            {localStatus}
          </div>
        )}
        {localError && (
          <div
            role="alert"
            className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-fg)]"
          >
            {localError}
          </div>
        )}

        <ConfigPanel variant="nested" headingLevel={4} title={t('model.contextWindowBudget')}>
          <p className="-mt-2 mb-4 text-xs text-[var(--text-muted)]">
            {t('model.contextWindowBudgetDescription')}
          </p>
          <FieldGrid cols={2} gap="md">
            <SectionField
              htmlFor="context-budget-max-tokens"
              label={t('model.workingContextMaxTokens')}
              description={t('model.runtimeDynamicDefaultDescription')}
            >
              <Input
                id="context-budget-max-tokens"
                type="number"
                value={readAgentYamlField(agentYaml, [
                  'context',
                  'budget_profile',
                  'max_tokens',
                ])}
                placeholder={t('model.runtimeDynamicDefault')}
                onChange={(e) =>
                  onFieldChange(
                    ['context', 'budget_profile', 'max_tokens'],
                    e.target.value,
                  )
                }
              />
            </SectionField>
            <SectionField
              htmlFor="context-budget-reserved-output"
              label={t('model.reservedOutputTokens')}
              description={t('model.reservedOutputTokensDescription')}
            >
              <Input
                id="context-budget-reserved-output"
                type="number"
                value={readAgentYamlField(agentYaml, [
                  'context',
                  'budget_profile',
                  'reserved_output_tokens',
                ])}
                placeholder={t('model.runtimeDynamicDefault')}
                onChange={(e) =>
                  onFieldChange(
                    ['context', 'budget_profile', 'reserved_output_tokens'],
                    e.target.value,
                  )
                }
              />
            </SectionField>
          </FieldGrid>
        </ConfigPanel>

        {/* ReAct controls section */}
        <ConfigPanel variant="nested" headingLevel={4} title={t('model.reactControls')}>
          <p className="-mt-2 mb-4 text-xs text-[var(--text-muted)]">
            {t('model.reactControlsDescription')}
          </p>
          <FieldGrid cols={3} gap="md">
            <SectionField htmlFor="react-max-steps" label="Max ReAct Steps">
              <Input
                id="react-max-steps"
                type="number"
                value={readAgentYamlField(agentYaml, ['react', 'max_steps'])}
                onChange={(e) => onFieldChange(['react', 'max_steps'], e.target.value)}
              />
            </SectionField>
            <SectionField htmlFor="react-max-tool-calls" label="Max Tool Calls">
              <Input
                id="react-max-tool-calls"
                type="number"
                value={readAgentYamlField(agentYaml, ['react', 'max_tool_calls'])}
                onChange={(e) =>
                  onFieldChange(['react', 'max_tool_calls'], e.target.value)
                }
              />
            </SectionField>
            <SectionField
              htmlFor="react-record-reasoning"
              label="Record Reasoning"
              description="Persist a reasoning summary on each run for audit."
              inline
            >
              <Switch
                id="react-record-reasoning"
                checked={recordReasoning}
                onCheckedChange={(checked) =>
                  onFieldChange(recordReasoningPath, checked ? 'true' : 'false')
                }
              />
            </SectionField>
          </FieldGrid>
        </ConfigPanel>
      </div>
    </ConfigPanel>
  )
}

function ModelRoleCard({
  role,
  agentYaml,
  modelConnections,
  unified = false,
  extraFields,
  onSourceChange,
  onFieldChange,
  onSaveAsShared,
  creatingShared = false,
}: {
  role: ModelRole
  agentYaml: string
  modelConnections: readonly SharedModelConnection[]
  unified?: boolean
  extraFields?: ReactNode
  onSourceChange: (value: string) => void
  onFieldChange: (path: string[], value: string) => void
  onSaveAsShared?: () => void
  creatingShared?: boolean
}) {
  const { t } = useLocale()
  const customSelected = currentModelSource(agentYaml, role.basePath) !== 'shared'
  const basePath = unified ? ['model'] : role.basePath
  const currentConnectionId = currentSharedConnectionId(agentYaml, role.basePath)
  const selectableConnections = selectableModelConnections(
    modelConnections,
    currentConnectionId,
  )
  const currentConnection = currentConnectionId
    ? modelConnections.find(
        (connection) => connection.connection_id === currentConnectionId,
      )
    : undefined
  const labelPrefix = unified ? '' : role.title.replace(' Model', '')
  const provider = readAgentYamlField(agentYaml, [...basePath, 'provider'])
  const modelName = readAgentYamlField(agentYaml, [...basePath, 'name'])
  const effectiveProvider = provider || MODEL_PROVIDER_OPTIONS[0]
  const effectiveModelName = modelName || 'deepseek-chat'
  const credentialName =
    readAgentYamlField(agentYaml, [...basePath, 'params', 'api_key_env']) ||
    readAgentYamlField(agentYaml, [...basePath, 'credential_ref', 'name'])
  const baseUrlEnv =
    readAgentYamlField(agentYaml, [...basePath, 'params', 'base_url_env']) ||
    readAgentYamlField(agentYaml, [...basePath, 'base_url'])
  const credentialPath = fieldPath(basePath, unified, ['params', 'api_key_env'])
  const baseUrlEnvPath = fieldPath(basePath, unified, ['params', 'base_url_env'])
  const temperaturePath = fieldPath(basePath, unified, ['params', 'temperature'])
  const maxOutputPath = fieldPath(basePath, unified, ['params', 'max_output_tokens'])
  const timeoutPath = fieldPath(basePath, unified, ['params', 'timeout_seconds'])
  const deepseekEndpointModePath = fieldPath(basePath, unified, [
    'params',
    'deepseek_endpoint_mode',
  ])
  const timeoutDefault =
    currentConnection?.timeout_seconds?.toString() ?? DEFAULT_TIMEOUT_SECONDS
  const showDeepSeekEndpointMode = roleUsesDeepSeek(
    customSelected,
    effectiveProvider,
    currentConnection,
  )

  const sourceId = `model-source-${role.basePath.join('-')}`
  const providerId = `model-provider-${role.basePath.join('-')}`
  const nameId = `model-name-${role.basePath.join('-')}`
  const keyEnvId = `model-key-env-${role.basePath.join('-')}`
  const baseUrlId = `model-base-url-${role.basePath.join('-')}`
  const deepseekEndpointModeId = `model-deepseek-endpoint-${role.basePath.join('-')}`
  const tempId = `model-temperature-${role.basePath.join('-')}`
  const maxTokensId = `model-max-tokens-${role.basePath.join('-')}`
  const timeoutId = `model-timeout-${role.basePath.join('-')}`

  const modelNameSuggestions =
    MODEL_NAME_SUGGESTIONS[effectiveProvider] ?? []

  return (
    <ConfigPanel
      variant="nested"
      headingLevel={4}
      title={
        <span className="flex min-w-0 items-center gap-2">
          {role.title}
          {role.reviewer && <Badge variant="subtle">reviewer</Badge>}
        </span>
      }
      description={role.subtitle}
    >
      {extraFields}
      <FieldGrid cols={2} gap="md">
        <SectionField htmlFor={sourceId} label={role.sourceLabel}>
          <NativeSelect
            id={sourceId}
            value={currentModelSourceValue(agentYaml, role.basePath)}
            onChange={onSourceChange}
            options={[
              ...selectableConnections.map((connection) => ({
                value: `shared:${connection.connection_id}`,
                label:
                  connection.lifecycle_state === 'ARCHIVED'
                    ? `${connection.display_name} (archived)`
                    : connection.display_name,
              })),
              { value: 'custom', label: 'Custom' },
            ]}
          />
        </SectionField>
        {currentConnection?.lifecycle_state === 'ARCHIVED' && (
          <div className="self-end rounded-md border border-[var(--warning-border)] bg-[var(--warning-bg)] px-3 py-2 text-xs font-medium text-[var(--warning-fg)]">
            {t('model.archivedConnection')}
          </div>
        )}
        {customSelected && (
          <>
            <SectionField
              htmlFor={providerId}
              label={`${labelPrefix ? `${labelPrefix} ` : ''}Provider`}
            >
              <NativeSelect
                id={providerId}
                value={effectiveProvider}
                onChange={(value) =>
                  onFieldChange(fieldPath(basePath, unified, ['provider']), value)
                }
                options={MODEL_PROVIDER_OPTIONS.map((option) => ({
                  value: option,
                  label: option,
                }))}
              />
            </SectionField>
            <SectionField
              htmlFor={nameId}
              label={`${labelPrefix ? `${labelPrefix} ` : ''}Model Name`}
              badge={
                modelNameSuggestions.length ? (
                  <Badge variant="outline" className="text-[10px]">
                    suggestions
                  </Badge>
                ) : undefined
              }
            >
              <Input
                id={nameId}
                list={`${nameId}-list`}
                value={modelName}
                placeholder="deepseek-chat"
                onChange={(e) =>
                  onFieldChange(fieldPath(basePath, unified, ['name']), e.target.value)
                }
              />
              {modelNameSuggestions.length > 0 && (
                <datalist id={`${nameId}-list`}>
                  {modelNameSuggestions.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              )}
            </SectionField>
            <SectionField
              htmlFor={keyEnvId}
              label={`${labelPrefix ? `${labelPrefix} ` : ''}API Key Env`}
            >
              <Input
                id={keyEnvId}
                translate="no"
                value={credentialName}
                placeholder="OPENAI_COMPATIBLE_API_KEY"
                onChange={(e) => {
                  onFieldChange(credentialPath, e.target.value)
                  if (currentModelSource(agentYaml, role.basePath) === 'custom') {
                    onFieldChange(
                      fieldPath(basePath, unified, ['credential_ref', 'name']),
                      e.target.value,
                    )
                  }
                }}
              />
            </SectionField>
            <SectionField
              htmlFor={baseUrlId}
              label={`${labelPrefix ? `${labelPrefix} ` : ''}Base URL Env`}
            >
              <Input
                id={baseUrlId}
                translate="no"
                value={baseUrlEnv}
                placeholder="OPENAI_COMPATIBLE_BASE_URL"
                onChange={(e) => onFieldChange(baseUrlEnvPath, e.target.value)}
              />
            </SectionField>
            {onSaveAsShared && (
              <div className="flex items-end">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onSaveAsShared}
                  disabled={creatingShared || !effectiveProvider || !effectiveModelName}
                >
                  {creatingShared ? t('model.creating') : t('model.saveAsShared')}
                </Button>
              </div>
            )}
          </>
        )}
        {showDeepSeekEndpointMode && (
          <SectionField
            htmlFor={deepseekEndpointModeId}
            label={`${labelPrefix ? `${labelPrefix} ` : ''}DeepSeek Endpoint`}
          >
            <NativeSelect
              id={deepseekEndpointModeId}
              value={deepseekEndpointModeValue(agentYaml, [
                ...basePath,
                'params',
                'deepseek_endpoint_mode',
              ])}
              onChange={(value) => onFieldChange(deepseekEndpointModePath, value)}
              options={[
                { value: 'beta', label: 'Beta (/beta)' },
                { value: 'standard', label: 'Standard' },
              ]}
            />
          </SectionField>
        )}
        <SectionField htmlFor={tempId} label={`${labelPrefix ? `${labelPrefix} ` : ''}Temperature`}>
          <Input
            id={tempId}
            type="number"
            value={usageControlValue(
              agentYaml,
              [...basePath, 'params', 'temperature'],
              DEFAULT_TEMPERATURE,
            )}
            onChange={(e) => onFieldChange(temperaturePath, e.target.value)}
          />
        </SectionField>
        <SectionField
          htmlFor={maxTokensId}
          label={`${labelPrefix ? `${labelPrefix} ` : ''}Max Output Tokens`}
        >
          <Input
            id={maxTokensId}
            type="number"
            value={usageControlValue(
              agentYaml,
              [...basePath, 'params', 'max_output_tokens'],
              DEFAULT_MAX_OUTPUT_TOKENS,
            )}
            onChange={(e) => onFieldChange(maxOutputPath, e.target.value)}
          />
        </SectionField>
        <SectionField htmlFor={timeoutId} label={`${labelPrefix ? `${labelPrefix} ` : ''}Timeout (s)`}>
          <Input
            id={timeoutId}
            type="number"
            value={usageControlValue(
              agentYaml,
              [...basePath, 'params', 'timeout_seconds'],
              timeoutDefault,
            )}
            onChange={(e) => onFieldChange(timeoutPath, e.target.value)}
          />
        </SectionField>
      </FieldGrid>
    </ConfigPanel>
  )
}

/** Shared native select with the standard control styling. */
function NativeSelect({
  id,
  value,
  onChange,
  options,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
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
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

function fieldPath(basePath: string[], unified: boolean, suffix: string[]): string[] {
  return unified ? suffix : [...basePath, ...suffix]
}

function usageControlValue(
  agentYaml: string,
  path: string[],
  fallback: string,
): string {
  const value = readAgentYamlField(agentYaml, path)
  return value === '' ? fallback : value
}

function deepseekEndpointModeValue(agentYaml: string, path: string[]): string {
  const value = readAgentYamlField(agentYaml, path)
  return value === 'standard' ? 'standard' : DEFAULT_DEEPSEEK_ENDPOINT_MODE
}

function roleUsesDeepSeek(
  customSelected: boolean,
  provider: string,
  currentConnection: SharedModelConnection | undefined,
): boolean {
  if (customSelected) return provider === 'deepseek'
  return (
    currentConnection?.provider === 'deepseek' ||
    (currentConnection?.base_url ?? '').includes('api.deepseek.com')
  )
}

function modelConfigForSource(
  agentYaml: string,
  role: ModelRole,
  sourceValue: string,
): AgentYamlMapping {
  const params = usageParams(agentYaml, role.basePath)
  if (sourceValue.startsWith('shared:')) {
    return {
      model_source: 'shared',
      connection_id: sourceValue.slice('shared:'.length),
      ...(role.reviewer
        ? {
            fail_closed:
              readAgentYamlField(agentYaml, ['review', 'subagent', 'fail_closed']) ||
              'true',
          }
        : {}),
      ...(Object.keys(params).length > 0 ? { params } : {}),
    }
  }
  return {
    model_source: 'custom',
    provider:
      readAgentYamlField(agentYaml, [...role.basePath, 'provider']) || 'deepseek',
    name: readAgentYamlField(agentYaml, [...role.basePath, 'name']) || 'deepseek-chat',
    ...(readAgentYamlField(agentYaml, [...role.basePath, 'base_url'])
      ? { base_url: readAgentYamlField(agentYaml, [...role.basePath, 'base_url']) }
      : {}),
    credential_ref: {
      type: 'env',
      name:
        readAgentYamlField(agentYaml, [...role.basePath, 'credential_ref', 'name']) ||
        readAgentYamlField(agentYaml, [...role.basePath, 'params', 'api_key_env']),
    },
    ...(role.reviewer
      ? {
          fail_closed:
            readAgentYamlField(agentYaml, ['review', 'subagent', 'fail_closed']) ||
            'true',
        }
      : {}),
    ...(Object.keys(params).length > 0 ? { params } : {}),
  }
}

function sharedConnectionPayload(agentYaml: string, role: ModelRole) {
  const provider =
    readAgentYamlField(agentYaml, [...role.basePath, 'provider']) || 'deepseek'
  const modelIdentifier =
    readAgentYamlField(agentYaml, [...role.basePath, 'name']) || 'deepseek-chat'
  const baseUrl = readAgentYamlField(agentYaml, [...role.basePath, 'base_url'])
  const credentialEnv =
    readAgentYamlField(agentYaml, [...role.basePath, 'credential_ref', 'name']) ||
    readAgentYamlField(agentYaml, [...role.basePath, 'params', 'api_key_env'])
  const timeoutSeconds = readAgentYamlField(agentYaml, [
    ...role.basePath,
    'params',
    'timeout_seconds',
  ])
  return {
    display_name: `${role.title} Shared Model`,
    provider,
    model_identifier: modelIdentifier,
    ...(baseUrl ? { base_url: baseUrl } : {}),
    credential_ref: { type: 'env' as const, name: credentialEnv },
    timeout_seconds: timeoutSeconds ? Number(timeoutSeconds) : undefined,
  }
}

function usageParams(agentYaml: string, basePath: string[]): AgentYamlMapping {
  const params: AgentYamlMapping = {}
  for (const key of [
    'temperature',
    'max_output_tokens',
    'timeout_seconds',
    'deepseek_endpoint_mode',
  ]) {
    const value = readAgentYamlField(agentYaml, [...basePath, 'params', key])
    if (value !== '') params[key] = value
  }
  return params
}

function currentModelSource(agentYaml: string, basePath: string[]): string {
  return readAgentYamlField(agentYaml, [...basePath, 'model_source']) || 'inline'
}

function currentModelSourceValue(agentYaml: string, basePath: string[]): string {
  if (currentModelSource(agentYaml, basePath) === 'shared') {
    const connectionId = currentSharedConnectionId(agentYaml, basePath)
    return connectionId ? `shared:${connectionId}` : 'custom'
  }
  return 'custom'
}

function currentSharedConnectionId(agentYaml: string, basePath: string[]): string {
  return readAgentYamlField(agentYaml, [...basePath, 'connection_id'])
}

function selectableModelConnections(
  modelConnections: readonly SharedModelConnection[],
  currentConnectionId: string,
): readonly SharedModelConnection[] {
  return modelConnections.filter(
    (connection) =>
      connection.lifecycle_state === 'ACTIVE' ||
      (Boolean(currentConnectionId) &&
        connection.connection_id === currentConnectionId),
  )
}
