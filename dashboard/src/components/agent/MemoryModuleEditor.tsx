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

  // Provider Settings
  const providerPath = ['memory', 'provider']
  const provider = readAgentYamlField(agentYaml, providerPath) || 'session'

  // Case Scope
  const caseEnabledPath = ['memory', 'scopes', 'case', 'enabled']
  const caseRetentionPath = ['memory', 'scopes', 'case', 'retention_days']
  const caseMaxRecordsPath = ['memory', 'scopes', 'case', 'max_records']
  const caseAllowRestrictedPath = ['memory', 'scopes', 'case', 'allow_restricted']

  const caseEnabled = readAgentYamlField(agentYaml, caseEnabledPath) === 'true'
  const caseRetention = readAgentYamlField(agentYaml, caseRetentionPath) || '30'
  const caseMaxRecords = readAgentYamlField(agentYaml, caseMaxRecordsPath) || '100'
  const caseAllowRestricted =
    readAgentYamlField(agentYaml, caseAllowRestrictedPath) === 'true'

  // User Scope
  const userEnabledPath = ['memory', 'scopes', 'user', 'enabled']
  const userEnabled = readAgentYamlField(agentYaml, userEnabledPath) === 'true'

  // Shared Scope
  const sharedEnabledPath = ['memory', 'scopes', 'shared', 'enabled']
  const sharedEnabled = readAgentYamlField(agentYaml, sharedEnabledPath) === 'true'

  return (
    <div className="space-y-6">
      {/* SECTION 1: Storage Provider */}
      <ConfigPanel
        headingLevel={3}
        title={t('memory.storageLayer')}
        description={t('memory.storageDescription')}
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
            htmlFor="memory-provider"
            label={t('memory.provider')}
            description="Where memory records are persisted. Session is ephemeral; Local and Mem0 persist across runs."
          >
            <select
              id="memory-provider"
              value={provider}
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

      {/* SECTION 2: Memory Scopes Grid */}
      <ConfigPanel
        headingLevel={3}
        title={t('memory.scopes')}
        description={t('memory.scopesDescription')}
      >
        <FieldGrid cols={3} gap="md">
          {/* Card: Case Memory */}
          <div
            className={cn(
              'flex min-w-0 flex-col rounded-md border p-4 transition-colors',
              caseEnabled
                ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                : 'border-[var(--border)] bg-[var(--bg-base)]',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 font-semibold text-[var(--text-primary)]">
                {t('memory.caseMemory')}
              </span>
              <Switch
                aria-label={t('memory.toggleCase')}
                checked={caseEnabled}
                onCheckedChange={(checked) =>
                  onFieldChange(caseEnabledPath, checked ? 'true' : 'false')
                }
              />
            </div>
            <p className="mt-1 min-w-0 text-xs text-[var(--text-muted)]">
              {t('memory.caseDescription')}
            </p>

            {caseEnabled && (
              <div className="mt-4 space-y-3 border-t border-[var(--border)] pt-4">
                <SectionField
                  htmlFor="case-memory-retention-days"
                  label={t('memory.retentionDays')}
                >
                  <Input
                    id="case-memory-retention-days"
                    type="number"
                    value={caseRetention}
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
                    onChange={(e) => onFieldChange(caseMaxRecordsPath, e.target.value)}
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
                    onCheckedChange={(checked) =>
                      onFieldChange(
                        caseAllowRestrictedPath,
                        checked ? 'true' : 'false',
                      )
                    }
                  />
                </SectionField>
              </div>
            )}
          </div>

          {/* Card: User Memory */}
          <div
            className={cn(
              'flex min-w-0 flex-col rounded-md border p-4 transition-colors',
              userEnabled
                ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                : 'border-[var(--border)] bg-[var(--bg-base)]',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 font-semibold text-[var(--text-primary)]">
                {t('memory.userMemory')}
              </span>
              <Switch
                aria-label={t('memory.toggleUser')}
                checked={userEnabled}
                onCheckedChange={(checked) =>
                  onFieldChange(userEnabledPath, checked ? 'true' : 'false')
                }
              />
            </div>
            <p className="mt-1 min-w-0 text-xs text-[var(--text-muted)]">
              {t('memory.userDescription')}
            </p>
          </div>

          {/* Card: Shared Memory */}
          <div
            className={cn(
              'flex min-w-0 flex-col rounded-md border p-4 transition-colors',
              sharedEnabled
                ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                : 'border-[var(--border)] bg-[var(--bg-base)]',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 font-semibold text-[var(--text-primary)]">
                {t('memory.sharedMemory')}
              </span>
              <Switch
                aria-label={t('memory.toggleShared')}
                checked={sharedEnabled}
                onCheckedChange={(checked) =>
                  onFieldChange(sharedEnabledPath, checked ? 'true' : 'false')
                }
              />
            </div>
            <p className="mt-1 min-w-0 text-xs text-[var(--text-muted)]">
              {t('memory.sharedDescription')}
            </p>
          </div>
        </FieldGrid>
      </ConfigPanel>
    </div>
  )
}
