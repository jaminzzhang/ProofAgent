import { useState } from 'react'
import { Link } from 'react-router-dom'
import { importConfigAgent, updateConfigDraft } from '../api/client'
import { CreateAgentWizard } from '../components/agent/CreateAgentWizard'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useConfigAgents } from '../hooks/useConfigAgents'
import { useLocale } from '../i18n/locale'

export function AgentsPage() {
  const { agents, loading, error, refresh } = useConfigAgents()
  const [manifestPath, setManifestPath] = useState('examples/insurance_customer_service/agent.yaml')
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const { t, formatDateTime, formatNumber } = useLocale()

  async function handleImport() {
    setImporting(true)
    setImportError(null)
    try {
      await importConfigAgent({ manifest_path: manifestPath })
      refresh()
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err))
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">{t('agents.title')}</h2>
          <p className="text-sm text-[var(--text-muted)] mt-1">{t('agents.description')}</p>
        </div>
        <div className="flex w-full md:w-auto items-center gap-3">
          <button
            onClick={() => setWizardOpen(true)}
            className="shrink-0 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90"
          >
            {t('agents.create')}
          </button>
          <input
            value={manifestPath}
            onChange={(event) => setManifestPath(event.target.value)}
            className="min-w-0 md:w-80 bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
          />
          <button
            onClick={handleImport}
            disabled={importing || !manifestPath.trim()}
            className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {importing ? t('agents.importing') : t('agents.import')}
          </button>
        </div>
      </div>

      {importError && (
        <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
          {importError}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {loading ? (
        <div className="py-12 flex justify-center"><LoadingSpinner /></div>
      ) : agents.length === 0 ? (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
          <EmptyState message={t('agents.empty')} />
        </div>
      ) : (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Agent</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">{t('agents.drafts')}</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">{t('agents.activeVersion')}</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">{t('agents.updated')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {agents.map((agent) => (
                <tr key={agent.agent_id} className="group hover:bg-[var(--bg-hover)] transition-colors">
                  <td className="px-5 py-3">
                    {agent.latest_draft_id ? (
                      <Link
                        to={`/agents/${agent.agent_id}/drafts/${agent.latest_draft_id}`}
                        className="font-medium text-[var(--text-primary)] group-hover:text-[var(--accent)]"
                      >
                        {agent.display_name}
                      </Link>
                    ) : (
                      <span className="font-medium text-[var(--text-primary)]">{agent.display_name}</span>
                    )}
                    <div className="mt-1 max-w-xl truncate text-xs text-[var(--text-muted)]">{agent.purpose}</div>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-secondary)]">{formatNumber(agent.draft_count)}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-secondary)]">{agent.active_version_id ?? t('agents.unpublished')}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">
                    {agent.updated_at ? formatDateTime(agent.updated_at) : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateAgentWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={() => refresh()}
        onCreate={async (manifestPath, displayName, purpose) => {
          const agent = await importConfigAgent({ manifest_path: manifestPath })
          if (displayName || purpose) {
            await updateConfigDraft(agent.agent_id, agent.draft_id, {
              display_name: displayName || undefined,
              purpose: purpose || undefined,
            })
          }
          return agent
        }}
      />
    </div>
  )
}
