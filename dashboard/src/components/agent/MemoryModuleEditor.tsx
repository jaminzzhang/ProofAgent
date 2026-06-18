import React from 'react'
import { readAgentYamlField } from '../../utils/agentYaml'
import { useLocale } from '../../i18n/locale'

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
  const caseAllowRestricted = readAgentYamlField(agentYaml, caseAllowRestrictedPath) === 'true'

  // User Scope
  const userEnabledPath = ['memory', 'scopes', 'user', 'enabled']
  const userEnabled = readAgentYamlField(agentYaml, userEnabledPath) === 'true'

  // Shared Scope
  const sharedEnabledPath = ['memory', 'scopes', 'shared', 'enabled']
  const sharedEnabled = readAgentYamlField(agentYaml, sharedEnabledPath) === 'true'

  return (
    <div className="space-y-6">
      {/* SECTION 1: Storage Provider */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          {t('memory.storageLayer')}
        </h3>
        <p className="mt-1 text-sm text-[var(--text-muted)] mb-4">
          {t('memory.storageDescription')}
        </p>

        <div className="max-w-xs">
          <label
            htmlFor="memory-provider"
            className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]"
          >
            {t('memory.provider')}
          </label>
          <select
            id="memory-provider"
            value={provider}
            onChange={(e) => onFieldChange(providerPath, e.target.value)}
            className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="session">Session (In-Memory, Ephemeral)</option>
            <option value="local">Local Database (Persistent)</option>
            <option value="mem0">Mem0 (Cloud/Managed)</option>
          </select>
        </div>
      </div>

      {/* SECTION 2: Memory Scopes Grid */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              {t('memory.scopes')}
            </h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('memory.scopesDescription')}
            </p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3 items-start">
          
          {/* Card: Case Memory */}
          <div className={`rounded-md border p-4 transition-colors ${caseEnabled ? 'border-[var(--accent)] bg-[var(--accent)]/5' : 'border-[var(--border)] bg-[var(--bg-base)]'}`}>
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold text-[var(--text-primary)]">{t('memory.caseMemory')}</span>
              <button
                aria-label={t('memory.toggleCase')}
                onClick={() => onFieldChange(caseEnabledPath, caseEnabled ? 'false' : 'true')}
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${caseEnabled ? 'bg-[var(--accent)]' : 'bg-[var(--bg-hover)]'}`}
              >
                <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${caseEnabled ? 'translate-x-5' : 'translate-x-1'}`} />
              </button>
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-4">
              {t('memory.caseDescription')}
            </p>
            
            {caseEnabled && (
              <div className="space-y-3 mt-4 pt-4 border-t border-[var(--border)]">
                <div>
                  <label
                    htmlFor="case-memory-retention-days"
                    className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1"
                  >
                    {t('memory.retentionDays')}
                  </label>
                  <input
                    id="case-memory-retention-days"
                    type="number"
                    value={caseRetention}
                    onChange={(e) => onFieldChange(caseRetentionPath, e.target.value)}
                    className="w-full bg-[var(--bg-surface)] border border-[var(--border)] rounded px-2 py-1 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  />
                </div>
                <div>
                  <label
                    htmlFor="case-memory-max-records"
                    className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1"
                  >
                    {t('memory.maxRecords')}
                  </label>
                  <input
                    id="case-memory-max-records"
                    type="number"
                    value={caseMaxRecords}
                    onChange={(e) => onFieldChange(caseMaxRecordsPath, e.target.value)}
                    className="w-full bg-[var(--bg-surface)] border border-[var(--border)] rounded px-2 py-1 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  />
                </div>
                <div className="flex items-center justify-between pt-1">
                  <label
                    htmlFor="case-memory-allow-restricted"
                    className="block text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]"
                  >
                    {t('memory.allowRestricted')}
                  </label>
                  <input
                    id="case-memory-allow-restricted"
                    type="checkbox"
                    checked={caseAllowRestricted}
                    onChange={(e) => onFieldChange(caseAllowRestrictedPath, e.target.checked ? 'true' : 'false')}
                    className="accent-[var(--accent)]"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Card: User Memory */}
          <div className={`rounded-md border p-4 transition-colors ${userEnabled ? 'border-[var(--accent)] bg-[var(--accent)]/5' : 'border-[var(--border)] bg-[var(--bg-base)]'}`}>
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold text-[var(--text-primary)]">{t('memory.userMemory')}</span>
              <button
                aria-label={t('memory.toggleUser')}
                onClick={() => onFieldChange(userEnabledPath, userEnabled ? 'false' : 'true')}
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${userEnabled ? 'bg-[var(--accent)]' : 'bg-[var(--bg-hover)]'}`}
              >
                <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${userEnabled ? 'translate-x-5' : 'translate-x-1'}`} />
              </button>
            </div>
            <p className="text-xs text-[var(--text-muted)]">
              {t('memory.userDescription')}
            </p>
          </div>

          {/* Card: Shared Memory */}
          <div className={`rounded-md border p-4 transition-colors ${sharedEnabled ? 'border-[var(--accent)] bg-[var(--accent)]/5' : 'border-[var(--border)] bg-[var(--bg-base)]'}`}>
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold text-[var(--text-primary)]">{t('memory.sharedMemory')}</span>
              <button
                aria-label={t('memory.toggleShared')}
                onClick={() => onFieldChange(sharedEnabledPath, sharedEnabled ? 'false' : 'true')}
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${sharedEnabled ? 'bg-[var(--accent)]' : 'bg-[var(--bg-hover)]'}`}
              >
                <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${sharedEnabled ? 'translate-x-5' : 'translate-x-1'}`} />
              </button>
            </div>
            <p className="text-xs text-[var(--text-muted)]">
              {t('memory.sharedDescription')}
            </p>
          </div>

        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onSave}
            disabled={busy}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50 transition-colors"
          >
            {busy ? t('agentDetail.saving') : t('memory.saveMemory')}
          </button>
        </div>
      </div>
    </div>
  )
}
