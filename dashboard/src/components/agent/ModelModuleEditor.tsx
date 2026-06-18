import { useState } from 'react'
import type { AgentYamlMapping } from '../../utils/agentYaml'
import { CodeBlock } from '../CodeBlock'
import type { SharedModelConnection } from '../../api/types'
import { extractAgentYamlSection, readAgentYamlField } from '../../utils/agentYaml'
import { useLocale } from '../../i18n/locale'

const MODEL_PROVIDER_OPTIONS = ['deterministic', 'openai_compatible', 'openai', 'deepseek', 'azure_openai', 'anthropic']
const DEFAULT_TEMPERATURE = '0'
const DEFAULT_MAX_OUTPUT_TOKENS = '800'
const DEFAULT_TIMEOUT_SECONDS = '20'

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

const ROLE_PATHS = [ANSWER_ROLE.basePath, PLANNER_ROLE.basePath, REVIEWER_ROLE.basePath]

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
  ].filter(Boolean).join('\n')

  function applyModelConfig(path: string[], value: AgentYamlMapping) {
    onModelConfigChange?.(path, value)
  }

  function handleSourceChange(role: ModelRole, value: string) {
    const nextConfig = modelConfigForSource(agentYaml, role, value)
    applyModelConfig(role.basePath, nextConfig)
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
      const connection = await onCreateSharedModelConnection(sharedConnectionPayload(agentYaml, role))
      setLocalStatus(`Created shared model connection ${connection.connection_id}.`)
      if (window.confirm('Switch this role to the new Shared Model Connection?')) {
        applyModelConfig(role.basePath, modelConfigForSource(agentYaml, role, `shared:${connection.connection_id}`))
      }
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Unable to create shared model connection.')
    } finally {
      setCreatingShared(null)
    }
  }

  return (
    <div className="bg-[var(--bg-base)] border border-[var(--border)] rounded-lg">
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between border-b border-[var(--border)] p-5 bg-[var(--bg-surface)] rounded-t-lg">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {t('model.configuration')}
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">{t('model.description')}</p>
        </div>
        <div className="flex items-center gap-3 mt-4 md:mt-0">
          <div className="flex bg-[var(--bg-base)] rounded-md p-1 border border-[var(--border)]">
            <button
              onClick={() => setStrategy('unified')}
              className={`px-3 py-1.5 text-xs font-medium rounded-sm transition-colors ${
                strategy === 'unified' ? 'bg-[var(--accent)]/10 text-[var(--accent)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              {t('model.unifiedSetup')}
            </button>
            <button
              onClick={() => setStrategy('role-specific')}
              className={`px-3 py-1.5 text-xs font-medium rounded-sm transition-colors ${
                strategy === 'role-specific' ? 'bg-[var(--accent)]/10 text-[var(--accent)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              {t('model.roleSpecific')}
            </button>
          </div>
          <button
            onClick={() => setShowYaml(!showYaml)}
            className={`text-xs font-medium px-3 py-1.5 rounded-md transition-colors ${
              showYaml
                ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
            }`}
          >
            {showYaml ? t('moduleEditor.hideYaml') : t('moduleEditor.showYaml')}
          </button>
          <button
            onClick={onSave}
            disabled={busy}
            className="rounded-md border border-[var(--border)] bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90 disabled:opacity-50"
          >
            {busy ? t('agentDetail.saving') : t('model.saveConfig')}
          </button>
        </div>
      </div>

      {showYaml && (
        <div className="border-b border-[var(--border)] p-5 bg-[var(--bg-surface)]">
          <CodeBlock>{sectionYaml}</CodeBlock>
        </div>
      )}

      <div className="p-5 space-y-6">
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
            onSaveAsShared={() => handleSaveAsShared({
              title: 'Primary Model Settings',
              sourceLabel: 'Primary Model Source',
              basePath: ['model'],
            })}
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
                <div className="grid gap-4 md:grid-cols-2">
                  <SelectField
                    label="Review Mode"
                    value={readAgentYamlField(agentYaml, ['review', 'mode']) || 'rules_only'}
                    onChange={(value) => onFieldChange(['review', 'mode'], value)}
                    options={[
                      { value: 'rules_only', label: 'Rules Only' },
                      { value: 'auto', label: 'Auto' },
                    ]}
                  />
                  <SelectField
                    label="Fail Closed"
                    value={readAgentYamlField(agentYaml, ['review', 'subagent', 'fail_closed']) || 'true'}
                    onChange={(value) => onFieldChange(['review', 'subagent', 'fail_closed'], value)}
                    options={[
                      { value: 'true', label: 'true' },
                      { value: 'false', label: 'false' },
                    ]}
                  />
                </div>
              }
            />
          </div>
        )}

        {localStatus && (
          <div className="rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-4 py-3 text-sm text-[var(--success)]">
            {localStatus}
          </div>
        )}
        {localError && (
          <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
            {localError}
          </div>
        )}

        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm mt-8">
          <h4 className="text-sm font-bold uppercase tracking-wider text-[var(--text-primary)] mb-1">{t('model.reactControls')}</h4>
          <p className="text-xs text-[var(--text-muted)] mb-4">{t('model.reactControlsDescription')}</p>
          <div className="grid gap-4 md:grid-cols-3">
            <TextField
              type="number"
              label="Max ReAct Steps"
              value={readAgentYamlField(agentYaml, ['react', 'max_steps'])}
              onChange={(value) => onFieldChange(['react', 'max_steps'], value)}
            />
            <TextField
              type="number"
              label="Max Tool Calls"
              value={readAgentYamlField(agentYaml, ['react', 'max_tool_calls'])}
              onChange={(value) => onFieldChange(['react', 'max_tool_calls'], value)}
            />
            <SelectField
              label="Record Reasoning"
              value={readAgentYamlField(agentYaml, ['react', 'record_reasoning_summary']) || 'true'}
              onChange={(value) => onFieldChange(['react', 'record_reasoning_summary'], value)}
              options={[
                { value: 'true', label: 'true' },
                { value: 'false', label: 'false' },
              ]}
            />
          </div>
        </div>
      </div>
    </div>
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
  extraFields?: React.ReactNode
  onSourceChange: (value: string) => void
  onFieldChange: (path: string[], value: string) => void
  onSaveAsShared?: () => void
  creatingShared?: boolean
}) {
  const { t } = useLocale()
  const customSelected = currentModelSource(agentYaml, role.basePath) !== 'shared'
  const basePath = unified ? ['model'] : role.basePath
  const currentConnectionId = currentSharedConnectionId(agentYaml, role.basePath)
  const selectableConnections = selectableModelConnections(modelConnections, currentConnectionId)
  const currentConnection = currentConnectionId
    ? modelConnections.find((connection) => connection.connection_id === currentConnectionId)
    : undefined
  const labelPrefix = unified ? '' : role.title.replace(' Model', '')
  const provider = readAgentYamlField(agentYaml, [...basePath, 'provider'])
  const modelName = readAgentYamlField(agentYaml, [...basePath, 'name'])
  const effectiveProvider = provider || MODEL_PROVIDER_OPTIONS[0]
  const effectiveModelName = modelName || 'deepseek-chat'
  const credentialName = readAgentYamlField(agentYaml, [...basePath, 'credential_ref', 'name'])
    || readAgentYamlField(agentYaml, [...basePath, 'params', 'api_key_env'])
  const baseUrl = readAgentYamlField(agentYaml, [...basePath, 'base_url'])
  const temperaturePath = fieldPath(basePath, unified, ['params', 'temperature'])
  const maxOutputPath = fieldPath(basePath, unified, ['params', 'max_output_tokens'])
  const timeoutPath = fieldPath(basePath, unified, ['params', 'timeout_seconds'])
  const timeoutDefault = currentConnection?.timeout_seconds?.toString() ?? DEFAULT_TIMEOUT_SECONDS

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 mb-4 shadow-sm">
      <h4 className="text-sm font-bold uppercase tracking-wider text-[var(--text-primary)] mb-1">{role.title}</h4>
      {role.subtitle && <p className="text-xs text-[var(--text-muted)] mb-4">{role.subtitle}</p>}
      {extraFields && <div className="mb-4">{extraFields}</div>}
      <div className="grid gap-4 md:grid-cols-2">
        <SelectField
          label={role.sourceLabel}
          value={currentModelSourceValue(agentYaml, role.basePath)}
          onChange={onSourceChange}
          options={[
            ...selectableConnections.map((connection) => ({
              value: `shared:${connection.connection_id}`,
              label: connection.lifecycle_state === 'ARCHIVED'
                ? `${connection.display_name} (archived)`
                : connection.display_name,
            })),
            { value: 'custom', label: 'Custom' },
          ]}
        />
        {currentConnection?.lifecycle_state === 'ARCHIVED' && (
          <div className="self-end rounded-md border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-3 py-2 text-xs font-medium text-[var(--warning)]">
            {t('model.archivedConnection')}
          </div>
        )}
        {customSelected && (
          <>
            <SelectField
              label={`${labelPrefix ? `${labelPrefix} ` : ''}Provider`}
              value={effectiveProvider}
              onChange={(value) => onFieldChange(fieldPath(basePath, unified, ['provider']), value)}
              options={MODEL_PROVIDER_OPTIONS.map((option) => ({ value: option, label: option }))}
            />
            <TextField
              label={`${labelPrefix ? `${labelPrefix} ` : ''}Model Name`}
              value={modelName}
              onChange={(value) => onFieldChange(fieldPath(basePath, unified, ['name']), value)}
              placeholder="deepseek-chat"
            />
            <TextField
              label={`${labelPrefix ? `${labelPrefix} ` : ''}Credential Env`}
              value={credentialName}
              onChange={(value) => onFieldChange(fieldPath(basePath, unified, ['credential_ref', 'name']), value)}
              placeholder="DEEPSEEK_API_KEY"
            />
            <TextField
              label={`${labelPrefix ? `${labelPrefix} ` : ''}Base URL`}
              value={baseUrl}
              onChange={(value) => onFieldChange(fieldPath(basePath, unified, ['base_url']), value)}
              placeholder="https://api.deepseek.com"
            />
            {onSaveAsShared && (
              <div className="flex items-end">
                <button
                  onClick={onSaveAsShared}
                  disabled={creatingShared || !effectiveProvider || !effectiveModelName}
                  className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                >
                  {creatingShared ? t('model.creating') : t('model.saveAsShared')}
                </button>
              </div>
            )}
          </>
        )}
        <TextField
          type="number"
          label={`${labelPrefix ? `${labelPrefix} ` : ''}Temperature`}
          value={usageControlValue(agentYaml, [...basePath, 'params', 'temperature'], DEFAULT_TEMPERATURE)}
          onChange={(value) => onFieldChange(temperaturePath, value)}
        />
        <TextField
          type="number"
          label={`${labelPrefix ? `${labelPrefix} ` : ''}Max Output Tokens`}
          value={usageControlValue(agentYaml, [...basePath, 'params', 'max_output_tokens'], DEFAULT_MAX_OUTPUT_TOKENS)}
          onChange={(value) => onFieldChange(maxOutputPath, value)}
        />
        <TextField
          type="number"
          label={`${labelPrefix ? `${labelPrefix} ` : ''}Timeout (s)`}
          value={usageControlValue(agentYaml, [...basePath, 'params', 'timeout_seconds'], timeoutDefault)}
          onChange={(value) => onFieldChange(timeoutPath, value)}
        />
      </div>
    </div>
  )
}

function fieldPath(basePath: string[], unified: boolean, suffix: string[]): string[] {
  return unified ? suffix : [...basePath, ...suffix]
}

function usageControlValue(agentYaml: string, path: string[], fallback: string): string {
  const value = readAgentYamlField(agentYaml, path)
  return value === '' ? fallback : value
}

function modelConfigForSource(agentYaml: string, role: ModelRole, sourceValue: string): AgentYamlMapping {
  const params = usageParams(agentYaml, role.basePath)
  if (sourceValue.startsWith('shared:')) {
    return {
      model_source: 'shared',
      connection_id: sourceValue.slice('shared:'.length),
      ...(role.reviewer ? { fail_closed: readAgentYamlField(agentYaml, ['review', 'subagent', 'fail_closed']) || 'true' } : {}),
      ...(Object.keys(params).length > 0 ? { params } : {}),
    }
  }
  return {
    model_source: 'custom',
    provider: readAgentYamlField(agentYaml, [...role.basePath, 'provider']) || 'deepseek',
    name: readAgentYamlField(agentYaml, [...role.basePath, 'name']) || 'deepseek-chat',
    ...(readAgentYamlField(agentYaml, [...role.basePath, 'base_url'])
      ? { base_url: readAgentYamlField(agentYaml, [...role.basePath, 'base_url']) }
      : {}),
    credential_ref: {
      type: 'env',
      name: readAgentYamlField(agentYaml, [...role.basePath, 'credential_ref', 'name'])
        || readAgentYamlField(agentYaml, [...role.basePath, 'params', 'api_key_env']),
    },
    ...(role.reviewer ? { fail_closed: readAgentYamlField(agentYaml, ['review', 'subagent', 'fail_closed']) || 'true' } : {}),
    ...(Object.keys(params).length > 0 ? { params } : {}),
  }
}

function sharedConnectionPayload(agentYaml: string, role: ModelRole) {
  const provider = readAgentYamlField(agentYaml, [...role.basePath, 'provider']) || 'deepseek'
  const modelIdentifier = readAgentYamlField(agentYaml, [...role.basePath, 'name']) || 'deepseek-chat'
  const baseUrl = readAgentYamlField(agentYaml, [...role.basePath, 'base_url'])
  const credentialEnv = readAgentYamlField(agentYaml, [...role.basePath, 'credential_ref', 'name'])
    || readAgentYamlField(agentYaml, [...role.basePath, 'params', 'api_key_env'])
  const timeoutSeconds = readAgentYamlField(agentYaml, [...role.basePath, 'params', 'timeout_seconds'])
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
  for (const key of ['temperature', 'max_output_tokens', 'timeout_seconds']) {
    const value = readAgentYamlField(agentYaml, [...basePath, 'params', key])
    if (value !== '') params[key] = value
  }
  return params
}

function currentModelSource(agentYaml: string, basePath: string[]): string {
  return readAgentYamlField(agentYaml, [...basePath, 'model_source']) || 'custom'
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
      connection.lifecycle_state === 'ACTIVE'
      || (Boolean(currentConnectionId) && connection.connection_id === currentConnectionId),
  )
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  type?: 'text' | 'number'
}) {
  return (
    <label className="block">
      <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">
        {label}
      </span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
      />
    </label>
  )
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <label className="block">
      <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">
        {label}
      </span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}
