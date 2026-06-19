import { useState } from 'react'
import { Badge, Button, Input, Label } from '@proofagent/ui'
import { CodeBlock } from '../CodeBlock'
import { extractAgentYamlSection, readAgentYamlField } from '../../utils/agentYaml'
import { useLocale } from '../../i18n/locale'

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
  const { t } = useLocale()
  const [showYaml, setShowYaml] = useState(false)

  const sectionYaml = extractAgentYamlSection(agentYaml, yamlSection)

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <div className="flex flex-col gap-3 border-b border-[var(--border)] p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {title}
          </h3>
          {description && (
            <p className="mt-1 text-sm text-[var(--text-muted)]">{description}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setShowYaml(!showYaml)}>
            {showYaml ? t('moduleEditor.hideYaml') : t('moduleEditor.showYaml')}
          </Button>
          <Button variant="outline" size="sm" onClick={onSave} disabled={busy}>
            {busy ? t('moduleEditor.saving') : t('moduleEditor.save')}
          </Button>
        </div>
      </div>

      {showYaml && sectionYaml && (
        <div className="border-b border-[var(--border)] p-5">
          <CodeBlock>{sectionYaml}</CodeBlock>
        </div>
      )}

      {/*
        Field grid: each card is a single-column flow (label row on top, input
        below). This replaces the old left/right two-column card which produced
        label/value ghosting at certain widths. Label-above-input can never
        overlap regardless of viewport width.
      */}
      <div className="grid gap-4 p-5 xl:grid-cols-2">
        {fields.map((field) => {
          const fieldPath = field.path.join('.')
          const fieldId = `module-field-${fieldPath.replaceAll('.', '-')}`
          const value = readAgentYamlField(agentYaml, field.path)

          return (
            <div
              key={fieldPath}
              className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-base)] p-4"
            >
              {/* Label row: name on the left, mono path badge on the right */}
              <div className="flex items-start justify-between gap-3">
                <Label htmlFor={fieldId} className="text-sm text-[var(--text-primary)]">
                  {field.label}
                </Label>
                <Badge variant="subtle" className="shrink-0 font-mono text-[10px] font-normal">
                  {fieldPath}
                </Badge>
              </div>

              {field.description && (
                <p className="-mt-1 text-xs leading-5 text-[var(--text-secondary)]">
                  {field.description}
                </p>
              )}

              {/* Input below — always clearly separated from the label row */}
              {field.input === 'select' && field.options ? (
                <select
                  id={fieldId}
                  value={value}
                  onChange={(e) => onFieldChange(field.path, e.target.value)}
                  className="h-9 w-full appearance-none rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 pr-9 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  style={{
                    backgroundImage:
                      "url(\"data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%238a8a8a' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
                    backgroundRepeat: 'no-repeat',
                    backgroundPosition: 'right 0.625rem center',
                  }}
                >
                  {field.options.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              ) : (
                <Input
                  id={fieldId}
                  type={field.input}
                  value={value}
                  placeholder={field.placeholder}
                  onChange={(e) => onFieldChange(field.path, e.target.value)}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export type { FieldConfig, ModuleEditorProps }
