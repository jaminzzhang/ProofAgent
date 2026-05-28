import { useState } from 'react'
import { CodeBlock } from '../CodeBlock'

interface FieldConfig {
  label: string
  path: string[]
  input: 'text' | 'number' | 'select'
  options?: string[]
  description?: string
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

  const sectionYaml = extractSectionYaml(agentYaml, yamlSection)

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
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
        <div className="grid gap-4 md:grid-cols-2">
          {fields.map((field) => (
            <label key={field.path.join('.')} className="block">
              <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                {field.label}
              </span>
              {field.description && (
                <span className="block text-xs text-[var(--text-muted)] mb-2">{field.description}</span>
              )}
              {field.input === 'select' && field.options ? (
                <select
                  value={readFieldValue(agentYaml, field.path)}
                  onChange={(e) => onFieldChange(field.path, e.target.value)}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                >
                  {field.options.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.input}
                  value={readFieldValue(agentYaml, field.path)}
                  onChange={(e) => onFieldChange(field.path, e.target.value)}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                />
              )}
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}

function readFieldValue(agentYaml: string, path: string[]): string {
  const lines = agentYaml.split('\n')

  if (path.length === 1) {
    for (const line of lines) {
      const match = line.match(new RegExp(`^${path[0]}:\\s*(.*)$`))
      if (match) return parseYamlValue(match[1])
    }
    return ''
  }

  const sectionStart = findSectionStart(lines, path[0])
  if (sectionStart === -1) return ''

  if (path.length === 2) {
    for (let i = sectionStart + 1; i < lines.length; i++) {
      if (lines[i].trim() && !lines[i].startsWith(' ')) break
      const match = lines[i].match(new RegExp(`^  ${path[1]}:\\s*(.*)$`))
      if (match) return parseYamlValue(match[1])
    }
    return ''
  }

  if (path.length === 3) {
    let parentStart = -1
    let parentEnd = lines.length
    for (let i = sectionStart + 1; i < lines.length; i++) {
      if (lines[i].trim() && !lines[i].startsWith(' ')) break
      if (lines[i].match(new RegExp(`^  ${path[1]}:`))) {
        parentStart = i
      } else if (parentStart !== -1 && lines[i].trim() && !lines[i].startsWith('    ')) {
        parentEnd = i
        break
      }
    }
    if (parentStart === -1) return ''
    for (let i = parentStart + 1; i < parentEnd; i++) {
      const match = lines[i].match(new RegExp(`^    ${path[2]}:\\s*(.*)$`))
      if (match) return parseYamlValue(match[1])
    }
    return ''
  }

  return ''
}

function extractSectionYaml(agentYaml: string, sectionName: string): string {
  const lines = agentYaml.split('\n')
  const start = findSectionStart(lines, sectionName)
  if (start === -1) return ''

  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].trim() && !lines[i].startsWith(' ')) {
      end = i
      break
    }
  }
  return lines.slice(start, end).join('\n')
}

function findSectionStart(lines: string[], sectionName: string): number {
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].match(new RegExp(`^${sectionName}:`))) return i
  }
  return -1
}

function parseYamlValue(value: string): string {
  const trimmed = value.trim()
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1)
  }
  return trimmed
}

export type { FieldConfig, ModuleEditorProps }
