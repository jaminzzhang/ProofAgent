import { useState } from 'react'
import { CodeBlock } from '../CodeBlock'
import { extractAgentYamlSection, readAgentYamlField } from '../../utils/agentYaml'

interface FieldConfig {
  label: string
  path: string[]
  input: 'text' | 'number' | 'select'
  options?: string[]
  description?: string
  placeholder?: string
}

interface ModuleEditorProps {
  title: string
  description?: string
  fields: FieldConfig[]
  yamlSection: string
  agentYaml: string
  onFieldChange: (path: string[], value: string) => void
  onSave: () => void
  busy: boolean
}

export function ModuleEditor({
  title,
  description,
  fields,
  yamlSection,
  agentYaml,
  onFieldChange,
  onSave,
  busy,
}: ModuleEditorProps) {
  const [showYaml, setShowYaml] = useState(false)

  const sectionYaml = extractAgentYamlSection(agentYaml, yamlSection)

  return (
    <div className="border border-[var(--border)] bg-[var(--bg-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] p-5">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {title}
          </h3>
          {description && (
            <p className="mt-1 text-sm text-[var(--text-muted)]">{description}</p>
          )}
        </div>
        <div className="flex items-center gap-3">
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
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {busy ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {showYaml && sectionYaml && (
        <div className="border-b border-[var(--border)] p-5">
          <CodeBlock>{sectionYaml}</CodeBlock>
        </div>
      )}

      <div className="p-5">
        <div className="grid gap-4 xl:grid-cols-2">
          {fields.map((field) => {
            const fieldPath = field.path.join('.')
            const fieldId = `module-field-${fieldPath.replaceAll('.', '-')}`

            return (
              <div key={fieldPath} className="grid min-w-0 gap-4 border border-[var(--border)] bg-[var(--bg-base)] p-4 md:grid-cols-[minmax(0,1fr)_minmax(220px,280px)]">
                <div className="min-w-0">
                  <label
                    htmlFor={fieldId}
                    className="block text-sm font-semibold text-[var(--text-primary)]"
                  >
                    {field.label}
                  </label>
                  {field.description && (
                    <p className="mt-1 text-sm leading-5 text-[var(--text-secondary)]">{field.description}</p>
                  )}
                  <p className="mt-3 break-all font-mono text-xs text-[var(--text-muted)]">{fieldPath}</p>
                </div>
                <div className="min-w-0">
                  {field.input === 'select' && field.options ? (
                    <select
                      id={fieldId}
                      value={readAgentYamlField(agentYaml, field.path)}
                      onChange={(e) => onFieldChange(field.path, e.target.value)}
                      className="w-full border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    >
                      {field.options.map((opt) => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id={fieldId}
                      type={field.input}
                      value={readAgentYamlField(agentYaml, field.path)}
                      placeholder={field.placeholder}
                      onChange={(e) => onFieldChange(field.path, e.target.value)}
                      className="w-full border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    />
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export type { FieldConfig, ModuleEditorProps }
