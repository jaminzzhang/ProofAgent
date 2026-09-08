import { useState } from 'react'
import {
  Badge,
  Button,
  ConfigPanel,
  FieldGrid,
  Input,
  SectionField,
  Switch,
} from '@proofagent/ui'
import { CodeBlock } from '../CodeBlock'
import { extractAgentYamlSection, extractAgentYamlPathSection, readAgentYamlField } from '../../utils/agentYaml'
import { useLocale } from '../../i18n/locale'

interface FieldConfig {
  label: string
  path: string[]
  /**
   * Control kind:
   *  - `text` / `number`: free-form input.
   *  - `select`: known values, native dropdown.
   *  - `switch`: boolean (renders as a toggle, value stored as 'true'/'false').
   *  - `combobox`: free-form input with autocomplete `options` suggestions.
   */
  input: 'text' | 'number' | 'select' | 'switch' | 'combobox'
  options?: string[]
  description?: string
  placeholder?: string
  defaultValue?: string
  min?: number
  max?: number
  step?: number
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

  const fieldValue = (field: FieldConfig) => extractAgentYamlPathSection(agentYaml, field.path)
    ? readAgentYamlField(agentYaml, field.path) : field.defaultValue || ''

  const errors = fields.map((field) => {
    if (field.input !== 'number' || field.min === undefined) return null
    const raw = fieldValue(field)
    const value = Number(raw)
    return !raw.trim() || !Number.isFinite(value) || value < field.min
      || (field.max !== undefined && value > field.max)
      || (field.step === 1 && !Number.isInteger(value))
      ? t('configuration.invalidNumber').replace('{field}', field.label)
      : null
  })

  return (
    <ConfigPanel
      title={title}
      description={description}
      headingLevel={3}
      actions={
        <>
          <Button variant="ghost" size="sm" onClick={() => setShowYaml(!showYaml)}>
            {showYaml ? t('moduleEditor.hideYaml') : t('moduleEditor.showYaml')}
          </Button>
          <Button variant="outline" size="sm" onClick={onSave} disabled={busy || errors.some(Boolean)}>
            {busy ? t('moduleEditor.saving') : t('moduleEditor.save')}
          </Button>
        </>
      }
      footer={
        showYaml && sectionYaml ? (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              {yamlSection}.yaml
            </h4>
            <CodeBlock>{sectionYaml}</CodeBlock>
          </div>
        ) : undefined
      }
      bodyPadding="default"
    >
      {/* Label-above-input cards. min-w-0 on every cell so long values
          truncate/wrap instead of pushing the grid. */}
      <FieldGrid cols={2} gap="md">
        {fields.map((field, index) => {
          const fieldPath = field.path.join('.')
          const fieldId = `module-field-${fieldPath.replaceAll('.', '-')}`
          const value = fieldValue(field)
          const pathBadge = (
            <Badge
              variant="subtle"
              translate="no"
              className="shrink-0 font-mono text-[10px] font-normal"
            >
              {fieldPath}
            </Badge>
          )

          return (
            <SectionField
              key={fieldPath}
              htmlFor={fieldId}
              label={field.label}
              description={field.description}
              badge={field.input === 'switch' ? undefined : pathBadge}
              inline={field.input === 'switch'}
            >
              {field.input === 'switch' ? (
                <Switch
                  id={fieldId}
                  checked={value === 'true'}
                  onCheckedChange={(checked) =>
                    onFieldChange(field.path, checked ? 'true' : 'false')
                  }
                  aria-label={field.label}
                />
              ) : field.input === 'select' && field.options ? (
                <select
                  id={fieldId}
                  value={value}
                  onChange={(e) => onFieldChange(field.path, e.target.value)}
                  className="h-9 w-full appearance-none rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 pr-9 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  style={{
                    // Native <select> chevron via data-URI. Can't read CSS vars,
                    // so use a mid-gray that stays legible in both light/dark.
                    backgroundImage:
                      "url(\"data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23737373' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
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
                  disabled={busy}
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  aria-invalid={Boolean(errors[index])}
                  aria-describedby={errors[index] ? `${fieldId}-error` : undefined}
                  type={field.input === 'number' ? 'number' : 'text'}
                  list={field.input === 'combobox' ? `${fieldId}-list` : undefined}
                  value={value}
                  placeholder={field.placeholder}
                  onChange={(e) => onFieldChange(field.path, e.target.value)}
                />
              )}
              {errors[index] && <p id={`${fieldId}-error`} role="alert" className="text-sm text-[var(--danger-fg)]">{errors[index]}</p>}
              {field.input === 'combobox' && field.options && (
                <datalist id={`${fieldId}-list`}>
                  {field.options.map((opt) => (
                    <option key={opt} value={opt} />
                  ))}
                </datalist>
              )}
            </SectionField>
          )
        })}
      </FieldGrid>
    </ConfigPanel>
  )
}

export type { FieldConfig, ModuleEditorProps }
