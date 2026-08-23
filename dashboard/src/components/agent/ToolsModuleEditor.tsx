import { useState } from 'react'
import {
  Button,
  ConfigPanel,
  FieldGrid,
  Input,
  SectionField,
  Switch,
} from '@proofagent/ui'
import { CodeBlock } from '../CodeBlock'
import {
  extractAgentYamlPathSection,
  readAgentYamlField,
} from '../../utils/agentYaml'
import { useLocale } from '../../i18n/locale'

interface ToolsModuleEditorProps {
  agentYaml: string
  onFieldChange: (path: string[], value: string) => void
  onSave: () => void
  busy: boolean
}

export function ToolsModuleEditor({
  agentYaml,
  onFieldChange,
  onSave,
  busy,
}: ToolsModuleEditorProps) {
  const { t } = useLocale()
  const [showYaml, setShowYaml] = useState(false)
  const enabledPath = ['capabilities', 'tools', 'enabled']
  const filePath = ['capabilities', 'tools', 'file']
  const enabled = readAgentYamlField(agentYaml, enabledPath) === 'true'
  const file = readAgentYamlField(agentYaml, filePath)
  const sectionYaml = extractAgentYamlPathSection(agentYaml, ['capabilities', 'tools'])

  return (
    <ConfigPanel
      headingLevel={3}
      title={t('agentDetail.toolsTitle')}
      description={t('agentDetail.toolsDescription')}
      actions={
        <>
          <Button variant="ghost" size="sm" onClick={() => setShowYaml(!showYaml)}>
            {showYaml ? t('moduleEditor.hideYaml') : t('moduleEditor.showYaml')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onSave}
            disabled={busy || (enabled && !file.trim())}
          >
            {busy ? t('moduleEditor.saving') : t('tools.save')}
          </Button>
        </>
      }
      footer={showYaml && sectionYaml ? <CodeBlock>{sectionYaml}</CodeBlock> : undefined}
    >
      <FieldGrid cols={2} gap="md">
        <SectionField
          htmlFor="tools-enabled"
          label={t('tools.enable')}
          description={t('tools.enableDescription')}
          inline
        >
          <Switch
            id="tools-enabled"
            aria-label={t('tools.enable')}
            checked={enabled}
            onCheckedChange={(checked) =>
              onFieldChange(enabledPath, checked ? 'true' : 'false')
            }
          />
        </SectionField>
        <SectionField
          htmlFor="tools-contract-file"
          label={t('tools.contractFile')}
          description={t('tools.contractFileDescription')}
        >
          <Input
            id="tools-contract-file"
            value={file}
            disabled={!enabled}
            placeholder="./tools.yaml"
            onChange={(event) => onFieldChange(filePath, event.target.value)}
          />
        </SectionField>
      </FieldGrid>
      {enabled && !file.trim() && (
        <p className="mt-3 text-xs text-[var(--danger)]" role="alert">
          {t('tools.contractFileRequired')}
        </p>
      )}
    </ConfigPanel>
  )
}
