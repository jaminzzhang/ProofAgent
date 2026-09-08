import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Bot, Search } from 'lucide-react'
import {
  Button,
  Card,
  EmptyState,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@proofagent/ui'
import { createConfigAgent, importConfigAgent } from '../api/client'
import { CreateAgentWizard } from '../components/agent/CreateAgentWizard'
import { useConfigAgents } from '../hooks/useConfigAgents'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'

export function AgentsPage() {
  const { agents, loading, error, capabilities, refresh } = useConfigAgents()
  const [manifestPath, setManifestPath] = useState(
    'examples/agent_management_insurance_specialist/agent.yaml',
  )
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<'all' | 'active' | 'unpublished'>('all')
  const visibleAgents = agents.filter(agent => {
    const matchesSearch = [agent.display_name, agent.agent_id, agent.purpose].join(' ').toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())
    return matchesSearch && (status === 'all' || (status === 'active' ? Boolean(agent.active_version_id) : !agent.active_version_id))
  })
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
    <div className="max-w-7xl space-y-5">
      <PageHeader
        title={t('agents.title')}
        description={t('agents.description')}
        actions={
          <>
            {capabilities?.can_create && (
              <Button variant="default" size="md" onClick={() => setWizardOpen(true)}>
                <Plus size={15} /> {t('agents.create').replace('+ ', '')}
              </Button>
            )}

          </>
        }
      />


      {capabilities?.can_import_manifest && (
        <details className="business-import">
          <summary>{t('business.importHelp')}</summary>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Input value={manifestPath} onChange={event => setManifestPath(event.target.value)}
              className="min-w-0 flex-1" aria-label={t('agents.import')} />
            <Button variant="outline" onClick={handleImport} disabled={importing || !manifestPath.trim()}>
              {importing ? t('agents.importing') : t('agents.import')}
            </Button>
          </div>
        </details>
      )}

      {!loading && !error && <dl className="business-summary">
        <div><dt>{t('business.total')}</dt><dd>{formatNumber(agents.length)}</dd></div>
        <div><dt>{t('business.active')}</dt><dd>{formatNumber(agents.filter(agent => agent.active_version_id).length)}</dd></div>
        <div><dt>{t('business.drafts')}</dt><dd>{formatNumber(agents.filter(agent => agent.latest_draft_id).length)}</dd></div>
      </dl>}

      {(importError || error) && (
        <div className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-fg)]">
          {importError || error}
        </div>
      )}

      {loading ? (
        <Card className="p-0">
          <TableSkeleton rows={4} columns={4} />
        </Card>
      ) : agents.length === 0 ? (
        <Card>
          <EmptyState message={t('agents.empty')} />
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="business-toolbar">
            <div className="relative min-w-0 flex-1 basis-64">
              <Search size={16} aria-hidden="true" className="absolute left-3 top-3 text-[var(--text-muted)]" />
              <Input type="search" className="pl-9" aria-label={t('business.search')} placeholder={t('business.search')}
                value={search} onChange={event => setSearch(event.target.value)} />
            </div>
            <div className="flex flex-wrap gap-1" role="group" aria-label={t('agents.activeVersion')}>
              {(['all', 'active', 'unpublished'] as const).map(value => <button type="button" key={value}
                className="business-filter" aria-pressed={status === value} onClick={() => setStatus(value)}>{t(`business.${value}`)}</button>)}
            </div>
          </div>
          <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
                <TableHead>{t('agents.title')}</TableHead>
                <TableHead>{t('agents.drafts')}</TableHead>
                <TableHead>{t('agents.activeVersion')}</TableHead>
                <TableHead>{t('agents.updated')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleAgents.map((agent) => (
                <TableRow key={agent.agent_id}>
                  <TableCell>
                    <div className="business-agent-name">
                    <span className="business-agent-icon" aria-hidden="true"><Bot size={19} /></span>
                    <div className="min-w-0">
                    {agent.latest_draft_id ? (
                      <Link
                        to={`/agents/${agent.agent_id}/drafts/${agent.latest_draft_id}`}
                        className="font-medium text-[var(--text-primary)] transition-colors hover:text-[var(--accent)]"
                      >
                        {agent.display_name}
                      </Link>
                    ) : (
                      <span className="font-medium text-[var(--text-primary)]">{agent.display_name}</span>
                    )}
                    <div className="mt-1 max-w-xl truncate text-xs text-[var(--text-muted)]">{agent.purpose}</div>
                    </div></div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--text-secondary)]">
                    {formatNumber(agent.draft_count)}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--text-secondary)]">
                    {agent.active_version_id ?? t('agents.unpublished')}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--text-muted)]">
                    {agent.updated_at ? formatDateTime(agent.updated_at) : '-'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
          {visibleAgents.length === 0 && <p role="status" className="px-6 py-12 text-center text-sm text-[var(--text-muted)]">{t('business.noResults')}</p>}
          <div className="border-t border-[var(--border)] px-5 py-3 text-xs text-[var(--text-muted)]" aria-live="polite">
            {t('business.results').replace('{count}', formatNumber(visibleAgents.length))}
          </div>
        </Card>
      )}

      {capabilities?.canonical_template && (
        <CreateAgentWizard
          open={wizardOpen}
          onClose={() => setWizardOpen(false)}
          onCreated={() => refresh()}
          template={capabilities.canonical_template}
          onCreate={(displayName, purpose, idempotencyKey) =>
            createConfigAgent(
              { display_name: displayName, purpose },
              idempotencyKey,
            )
          }
        />
      )}
    </div>
  )
}
