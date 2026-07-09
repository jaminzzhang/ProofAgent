import {
  Button,
  ConfigPanel,
  FieldGrid,
  Input,
  SectionField,
  Switch,
} from '@proofagent/ui'
import { readAgentYamlField } from '../../utils/agentYaml'
import { useLocale } from '../../i18n/locale'
import { cn } from '@proofagent/ui'

interface MemoryModuleEditorProps {
  agentYaml: string
  onFieldChange: (path: string[], value: string) => void
  onSave: () => void
  busy: boolean
}

export function MemoryModuleEditor({
  agentYaml,
  onFieldChange,
  onSave,
  busy,
}: MemoryModuleEditorProps) {
  const { t } = useLocale()

  const memoryEnabledPath = ['capabilities', 'memory', 'enabled']
  const providerPath = ['capabilities', 'memory', 'provider']
  const memoryEnabled = readAgentYamlField(agentYaml, memoryEnabledPath) === 'true'
  const provider = readAgentYamlField(agentYaml, providerPath) || 'session'

  const caseEnabledPath = ['capabilities', 'memory', 'scopes', 'case', 'enabled']
  const caseRetentionPath = ['capabilities', 'memory', 'scopes', 'case', 'retention_days']
  const caseMaxRecordsPath = ['capabilities', 'memory', 'scopes', 'case', 'max_records']
  const caseAllowRestrictedPath = ['capabilities', 'memory', 'scopes', 'case', 'allow_restricted']

  const caseEnabled = readAgentYamlField(agentYaml, caseEnabledPath) === 'true'
  const caseRetention = readAgentYamlField(agentYaml, caseRetentionPath) || '30'
  const caseMaxRecords = readAgentYamlField(agentYaml, caseMaxRecordsPath) || '5'
  const caseAllowRestricted =
    readAgentYamlField(agentYaml, caseAllowRestrictedPath) === 'true'

  const userEnabledPath = ['capabilities', 'memory', 'scopes', 'user', 'enabled']
  const userRetentionPath = ['capabilities', 'memory', 'scopes', 'user', 'retention_days']
  const userMaxRecordsPath = ['capabilities', 'memory', 'scopes', 'user', 'max_records']
  const userAllowRestrictedPath = ['capabilities', 'memory', 'scopes', 'user', 'allow_restricted']
  const userEnabled = readAgentYamlField(agentYaml, userEnabledPath) === 'true'
  const userRetention = readAgentYamlField(agentYaml, userRetentionPath) || '30'
  const userMaxRecords = readAgentYamlField(agentYaml, userMaxRecordsPath) || '5'
  const userAllowRestricted =
    readAgentYamlField(agentYaml, userAllowRestrictedPath) === 'true'

  const sharedEnabledPath = ['capabilities', 'memory', 'scopes', 'shared', 'enabled']
  const sharedEnabled = readAgentYamlField(agentYaml, sharedEnabledPath) === 'true'

  const memoryRecallCasePath = ['context', 'source_policies', 'memory_recall', 'scopes', 'case', 'enabled']
  const memoryRecallUserPath = ['context', 'source_policies', 'memory_recall', 'scopes', 'user', 'enabled']
  const memoryRecallSharedPath = ['context', 'source_policies', 'memory_recall', 'scopes', 'shared', 'enabled']
  const memoryRecallCase = caseEnabled && readAgentYamlField(agentYaml, memoryRecallCasePath) !== 'false'
  const memoryRecallUser = userEnabled && readAgentYamlField(agentYaml, memoryRecallUserPath) !== 'false'
  const memoryRecallShared = readAgentYamlField(agentYaml, memoryRecallSharedPath) === 'true'

  return (
    <div className="space-y-6">
      <ConfigPanel
        headingLevel={3}
        title={t('memory.providerEnablement')}
        description={t('memory.providerEnablementDescription')}
        footer={
          <div className="flex justify-end">
            <Button variant="outline" size="sm" onClick={onSave} disabled={busy}>
              {busy ? t('agentDetail.saving') : t('memory.saveMemory')}
            </Button>
          </div>
        }
      >
        <FieldGrid cols={2} gap="md">
          <SectionField
            htmlFor="memory-enabled"
            label={t('memory.enableMemory')}
            description={t('memory.enableMemoryDescription')}
            inline
          >
            <Switch
              id="memory-enabled"
              aria-label={t('memory.enableMemory')}
              checked={memoryEnabled}
              onCheckedChange={(checked) =>
                onFieldChange(memoryEnabledPath, checked ? 'true' : 'false')
              }
            />
          </SectionField>
          <SectionField
            htmlFor="memory-provider"
            label={t('memory.provider')}
            description={t('memory.providerDescription')}
          >
            <select
              id="memory-provider"
              value={provider}
              disabled={!memoryEnabled}
              onChange={(e) => onFieldChange(providerPath, e.target.value)}
              className="h-9 w-full appearance-none rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 pr-9 text-sm text-[var(--text-primary)] transition-colors focus:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
              style={{
                backgroundImage:
                  "url(\"data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23737373' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
                backgroundRepeat: 'no-repeat',
                backgroundPosition: 'right 0.625rem center',
              }}
            >
              <option value="session">Session (In-Memory, Ephemeral)</option>
              <option value="local">Local Database (Persistent)</option>
              <option value="mem0">Mem0 (Cloud/Managed)</option>
            </select>
          </SectionField>
        </FieldGrid>
      </ConfigPanel>

      <ConfigPanel
        headingLevel={3}
        title={t('memory.caseMemory')}
        description={t('memory.caseDescription')}
      >
        <div
          className={cn(
            'rounded-md border p-4',
            caseEnabled
              ? 'border-[var(--accent)] bg-[var(--accent)]/5'
              : 'border-[var(--border)] bg-[var(--bg-base)]',
          )}
          >
          <FieldGrid cols={2} gap="md">
            <SectionField
              htmlFor="case-memory-enabled"
              label={t('memory.caseMemory')}
              inline
            >
              <Switch
                id="case-memory-enabled"
                aria-label={t('memory.toggleCase')}
                checked={caseEnabled}
                disabled={!memoryEnabled}
                onCheckedChange={(checked) =>
                  onFieldChange(caseEnabledPath, checked ? 'true' : 'false')
                }
              />
            </SectionField>
            <SectionField
              htmlFor="case-memory-allow-restricted"
              label={t('memory.allowRestricted')}
              inline
            >
              <Switch
                id="case-memory-allow-restricted"
                checked={caseAllowRestricted}
                disabled={!memoryEnabled || !caseEnabled}
                onCheckedChange={(checked) =>
                  onFieldChange(
                    caseAllowRestrictedPath,
                    checked ? 'true' : 'false',
                  )
                }
              />
            </SectionField>
            <SectionField
              htmlFor="case-memory-retention-days"
              label={t('memory.retentionDays')}
            >
              <Input
                id="case-memory-retention-days"
                type="number"
                value={caseRetention}
                disabled={!memoryEnabled || !caseEnabled}
                onChange={(e) => onFieldChange(caseRetentionPath, e.target.value)}
              />
            </SectionField>
            <SectionField
              htmlFor="case-memory-max-records"
              label={t('memory.maxRecords')}
            >
              <Input
                id="case-memory-max-records"
                type="number"
                value={caseMaxRecords}
                disabled={!memoryEnabled || !caseEnabled}
                onChange={(e) => onFieldChange(caseMaxRecordsPath, e.target.value)}
              />
            </SectionField>
          </FieldGrid>
        </div>
      </ConfigPanel>

      <ConfigPanel
        headingLevel={3}
        title={t('memory.userMemory')}
        description={t('memory.userDescription')}
      >
        <FieldGrid cols={2} gap="md">
          <SectionField
            htmlFor="user-memory-enabled"
            label={t('memory.userMemory')}
            inline
          >
            <Switch
              id="user-memory-enabled"
              aria-label={t('memory.toggleUser')}
              checked={userEnabled}
              disabled={!memoryEnabled}
              onCheckedChange={(checked) =>
                onFieldChange(userEnabledPath, checked ? 'true' : 'false')
              }
            />
          </SectionField>
          <SectionField
            htmlFor="user-memory-allow-restricted"
            label={t('memory.allowRestricted')}
            inline
          >
            <Switch
              id="user-memory-allow-restricted"
              checked={userAllowRestricted}
              disabled={!memoryEnabled || !userEnabled}
              onCheckedChange={(checked) =>
                onFieldChange(
                  userAllowRestrictedPath,
                  checked ? 'true' : 'false',
                )
              }
            />
          </SectionField>
          <SectionField
            htmlFor="user-memory-retention-days"
            label={t('memory.retentionDays')}
          >
            <Input
              id="user-memory-retention-days"
              type="number"
              value={userRetention}
              disabled={!memoryEnabled || !userEnabled}
              onChange={(e) => onFieldChange(userRetentionPath, e.target.value)}
            />
          </SectionField>
          <SectionField
            htmlFor="user-memory-max-records"
            label={t('memory.maxRecords')}
          >
            <Input
              id="user-memory-max-records"
              type="number"
              value={userMaxRecords}
              disabled={!memoryEnabled || !userEnabled}
              onChange={(e) => onFieldChange(userMaxRecordsPath, e.target.value)}
            />
          </SectionField>
        </FieldGrid>
      </ConfigPanel>

      <ConfigPanel
        headingLevel={3}
        title={t('memory.sharedDisabled')}
        description={t('memory.sharedDescription')}
      >
        <FieldGrid cols={2} gap="md">
          <SectionField
            htmlFor="shared-memory-enabled"
            label={t('memory.sharedMemory')}
            description={t('memory.sharedGateReason')}
            inline
          >
            <Switch
              id="shared-memory-enabled"
              aria-label={t('memory.toggleShared')}
              checked={sharedEnabled}
              disabled
              onCheckedChange={(checked) =>
                onFieldChange(sharedEnabledPath, checked ? 'true' : 'false')
              }
            />
          </SectionField>
        </FieldGrid>
      </ConfigPanel>

      <ConfigPanel
        headingLevel={3}
        title={t('memory.recallAdmission')}
        description={t('memory.recallAdmissionDescription')}
      >
        <FieldGrid cols={3} gap="md">
          <SectionField htmlFor="memory-recall-case" label={t('memory.caseMemory')} inline>
            <Switch
              id="memory-recall-case"
              aria-label={t('memory.toggleCaseRecall')}
              checked={memoryRecallCase}
              disabled={!memoryEnabled || !caseEnabled}
              onCheckedChange={(checked) =>
                onFieldChange(memoryRecallCasePath, checked ? 'true' : 'false')
              }
            />
          </SectionField>
          <SectionField htmlFor="memory-recall-user" label={t('memory.userMemory')} inline>
            <Switch
              id="memory-recall-user"
              aria-label={t('memory.toggleUserRecall')}
              checked={memoryRecallUser}
              disabled={!memoryEnabled || !userEnabled}
              onCheckedChange={(checked) =>
                onFieldChange(memoryRecallUserPath, checked ? 'true' : 'false')
              }
            />
          </SectionField>
          <SectionField htmlFor="memory-recall-shared" label={t('memory.sharedMemory')} description={t('memory.sharedGateReason')} inline>
            <Switch
              id="memory-recall-shared"
              aria-label={t('memory.toggleSharedRecall')}
              checked={memoryRecallShared}
              disabled
              onCheckedChange={(checked) =>
                onFieldChange(memoryRecallSharedPath, checked ? 'true' : 'false')
              }
            />
          </SectionField>
        </FieldGrid>
      </ConfigPanel>

      <ConfigPanel
        headingLevel={3}
        title={t('memory.stageVisibility')}
        description={t('memory.stageVisibilityDescription')}
      >
        <div className="grid gap-2 text-sm text-[var(--text-secondary)] sm:grid-cols-2">
          <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
            {t('memory.stageIntentPlanning')}
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
            {t('memory.stageRetrievalQuery')}
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
            {t('memory.stageFinalAnswer')}
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
            {t('memory.stageToolBlocked')}
          </div>
        </div>
      </ConfigPanel>

      <ConfigPanel
        headingLevel={3}
        title={t('memory.lifecycleAudit')}
        description={t('memory.lifecycleAuditDescription')}
      >
        <div className="grid gap-2 text-sm text-[var(--text-secondary)] sm:grid-cols-2">
          <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
            {t('memory.lifecycleRetention')}
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
            {t('memory.lifecycleOperationsLater')}
          </div>
        </div>
      </ConfigPanel>
    </div>
  )
}
