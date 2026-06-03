import { useState } from 'react'
import { CodeBlock } from '../CodeBlock'
import { extractAgentYamlSection, readAgentYamlField } from '../../utils/agentYaml'

const MODEL_PROVIDER_OPTIONS = ['deterministic', 'openai_compatible', 'openai', 'deepseek', 'azure_openai', 'anthropic']

interface ModelModuleEditorProps {
  agentYaml: string
  onFieldChange: (path: string[], value: string) => void
  onSave: () => void
  busy: boolean
}

interface FieldDef {
  label: string
  input: 'text' | 'number' | 'select'
  options?: string[]
  placeholder?: string
  description?: string
}

const COMMON_MODEL_FIELDS: Record<string, FieldDef> = {
  provider: { label: 'Provider', input: 'select', options: MODEL_PROVIDER_OPTIONS },
  name: { label: 'Model Name', input: 'text', placeholder: 'deepseek-v4-flash' },
  api_key_env: { label: 'API Key Env', input: 'text', placeholder: 'DEEPSEEK_API_KEY', description: 'Environment variable for API key' },
  base_url_env: { label: 'Base URL Env', input: 'text', placeholder: 'DEEPSEEK_BASE_URL' },
  temperature: { label: 'Temperature', input: 'number' },
  max_output_tokens: { label: 'Max Output Tokens', input: 'number' },
  timeout_seconds: { label: 'Timeout (s)', input: 'number' }
}

export function ModelModuleEditor({
  agentYaml,
  onFieldChange,
  onSave,
  busy,
}: ModelModuleEditorProps) {
  const [strategy, setStrategy] = useState<'unified' | 'role-specific'>('unified')
  const [showYaml, setShowYaml] = useState(false)

  const sectionYaml = extractAgentYamlSection(agentYaml, 'model') + '\n' + extractAgentYamlSection(agentYaml, 'react') + '\n' + extractAgentYamlSection(agentYaml, 'review')

  const handleUnifiedChange = (subPath: string[], value: string) => {
    // Determine the three paths
    // Answer
    const answerPath = ['model', ...subPath]
    // Planner
    const plannerPath = ['react', 'planner', ...subPath]
    // Reviewer
    const reviewerPath = ['review', 'subagent', ...subPath]
    
    // Call sequentially (React state functional updaters will handle this gracefully)
    onFieldChange(answerPath, value)
    onFieldChange(plannerPath, value)
    onFieldChange(reviewerPath, value)
  }

  const renderModelFields = (basePath: string[], isUnified: boolean, title: string, subtitle?: string, extraFields?: React.ReactNode) => {
    const getPath = (key: string) => {
      if (key === 'provider' || key === 'name') return [...basePath, key]
      return [...basePath, 'params', key]
    }
    
    // For Reviewer: Max output tokens and timeout are sometimes outside params or inside. Wait, looking at model.ts:
    // Reviewer Max Output Tokens is ['review', 'subagent', 'max_output_tokens'] (outside params!)
    // Let's use specific hardcoded paths for each if needed, but for Unified it's tricky if paths diverge.
    // In model.ts:
    // Answer: model.params.max_output_tokens
    // Planner: react.planner.params.max_output_tokens
    // Reviewer: review.subagent.max_output_tokens (Wait, is this a typo in model.ts or YAML contract?)
    // In ProofAgent CONTEXT, Reviewer subagent might just have max_output_tokens natively. Let's stick to the paths defined in model.ts.
    
    return (
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 mb-4 shadow-sm">
        <h4 className="text-sm font-bold uppercase tracking-wider text-[var(--text-primary)] mb-1">{title}</h4>
        {subtitle && <p className="text-xs text-[var(--text-muted)] mb-4">{subtitle}</p>}
        {extraFields && <div className="mb-4">{extraFields}</div>}
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(COMMON_MODEL_FIELDS).map(([key, def]) => {
            // Path resolution
            let resolvedPath = [...basePath]
            if (key === 'provider' || key === 'name') {
              resolvedPath.push(key)
            } else {
              // Handle the Reviewer divergence for timeout and max_tokens
              if (basePath[0] === 'review' && (key === 'max_output_tokens' || key === 'timeout_seconds')) {
                resolvedPath.push(key)
              } else {
                resolvedPath.push('params', key)
              }
            }

            const val = readAgentYamlField(agentYaml, resolvedPath)

            return (
              <label key={key} className="block">
                <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">
                  {def.label}
                </span>
                {def.description && (
                  <span className="block text-xs text-[var(--text-muted)] mb-2">{def.description}</span>
                )}
                {def.input === 'select' && def.options ? (
                  <select
                    value={val}
                    onChange={(e) => isUnified ? handleUnifiedChange(key === 'provider' || key === 'name' ? [key] : (key === 'max_output_tokens' || key === 'timeout_seconds') ? ['params', key] : ['params', key], e.target.value) : onFieldChange(resolvedPath, e.target.value)}
                    className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  >
                    {def.options.map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={def.input}
                    value={val}
                    placeholder={def.placeholder}
                    onChange={(e) => {
                      if (isUnified) {
                        // For unified change, we need to map the subpath carefully
                        if (key === 'provider' || key === 'name') {
                          handleUnifiedChange([key], e.target.value)
                        } else if (key === 'max_output_tokens' || key === 'timeout_seconds') {
                          // The tricky part: Reviewer uses direct keys, Answer/Planner use params.key
                          // We must explicitly call onFieldChange for the 3 roles because handleUnifiedChange assumes consistent subpath
                          onFieldChange(['model', 'params', key], e.target.value)
                          onFieldChange(['react', 'planner', 'params', key], e.target.value)
                          onFieldChange(['review', 'subagent', key], e.target.value)
                        } else {
                          handleUnifiedChange(['params', key], e.target.value)
                        }
                      } else {
                        onFieldChange(resolvedPath, e.target.value)
                      }
                    }}
                    className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  />
                )}
              </label>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="bg-[var(--bg-base)] border border-[var(--border)] rounded-lg">
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between border-b border-[var(--border)] p-5 bg-[var(--bg-surface)] rounded-t-lg">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Model Configuration
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Configure models for Answer, Planner, and Reviewer roles</p>
        </div>
        <div className="flex items-center gap-3 mt-4 md:mt-0">
          <div className="flex bg-[var(--bg-base)] rounded-md p-1 border border-[var(--border)]">
            <button
              onClick={() => setStrategy('unified')}
              className={`px-3 py-1.5 text-xs font-medium rounded-sm transition-colors ${
                strategy === 'unified' ? 'bg-[var(--accent)]/10 text-[var(--accent)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              Unified Setup
            </button>
            <button
              onClick={() => setStrategy('role-specific')}
              className={`px-3 py-1.5 text-xs font-medium rounded-sm transition-colors ${
                strategy === 'role-specific' ? 'bg-[var(--accent)]/10 text-[var(--accent)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              Role-Specific
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
            {showYaml ? 'Hide YAML' : 'Show YAML'}
          </button>
          <button
            onClick={onSave}
            disabled={busy}
            className="rounded-md border border-[var(--border)] bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90 disabled:opacity-50"
          >
            {busy ? 'Saving...' : 'Save Config'}
          </button>
        </div>
      </div>

      {showYaml && (
        <div className="border-b border-[var(--border)] p-5 bg-[var(--bg-surface)]">
          <CodeBlock>{sectionYaml}</CodeBlock>
        </div>
      )}

      <div className="p-5 space-y-6">
        {/* Model Configurations */}
        {strategy === 'unified' ? (
          renderModelFields(
            ['model'], 
            true, 
            'Primary Model Settings', 
            'These settings will be applied to the Answer, Planner, and Reviewer roles simultaneously.'
          )
        ) : (
          <div className="space-y-6">
            {renderModelFields(['model'], false, 'Answer Model', 'Final answer generation model')}
            {renderModelFields(['react', 'planner'], false, 'Planner Model', 'ReAct reasoning and tool planning model')}
            {renderModelFields(
              ['review', 'subagent'], 
              false, 
              'Reviewer Model', 
              'Harness review subagent model',
              <div className="grid gap-4 md:grid-cols-2">
                <label className="block">
                  <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">Review Mode</span>
                  <select
                    value={readAgentYamlField(agentYaml, ['review', 'mode'])}
                    onChange={(e) => onFieldChange(['review', 'mode'], e.target.value)}
                    className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  >
                    <option value="rules_only">Rules Only</option>
                    <option value="auto">Auto (LLM Subagent)</option>
                  </select>
                </label>
                <label className="block">
                  <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">Fail Closed</span>
                  <select
                    value={readAgentYamlField(agentYaml, ['review', 'subagent', 'fail_closed'])}
                    onChange={(e) => onFieldChange(['review', 'subagent', 'fail_closed'], e.target.value)}
                    className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                </label>
              </div>
            )}
          </div>
        )}

        {/* ReAct Execution Controls */}
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm mt-8">
          <h4 className="text-sm font-bold uppercase tracking-wider text-[var(--text-primary)] mb-1">ReAct Execution Controls</h4>
          <p className="text-xs text-[var(--text-muted)] mb-4">Bounds and settings for the ReAct planning loop</p>
          <div className="grid gap-4 md:grid-cols-3">
            <label className="block">
              <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">Max ReAct Steps</span>
              <input
                type="number"
                value={readAgentYamlField(agentYaml, ['react', 'max_steps'])}
                onChange={(e) => onFieldChange(['react', 'max_steps'], e.target.value)}
                className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </label>
            <label className="block">
              <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">Max Tool Calls</span>
              <input
                type="number"
                value={readAgentYamlField(agentYaml, ['react', 'max_tool_calls'])}
                onChange={(e) => onFieldChange(['react', 'max_tool_calls'], e.target.value)}
                className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </label>
            <label className="block">
              <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">Record Reasoning</span>
              <select
                value={readAgentYamlField(agentYaml, ['react', 'record_reasoning_summary'])}
                onChange={(e) => onFieldChange(['react', 'record_reasoning_summary'], e.target.value)}
                className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            </label>
          </div>
        </div>
      </div>
    </div>
  )
}
