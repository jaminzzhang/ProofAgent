import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
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
import { importConfigAgent, updateConfigDraft } from '../api/client'
import { CreateAgentWizard } from '../components/agent/CreateAgentWizard'
import { useConfigAgents } from '../hooks/useConfigAgents'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'

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
    <div className="max-w-7xl space-y-5">
      <PageHeader
        title={t('agents.title')}
        description={t('agents.description')}
        actions={
          <>
            <Button variant="outline" size="md" onClick={() => setWizardOpen(true)}>
              <Plus size={15} /> {t('agents.create').replace('+ ', '')}
            </Button>
            <Input
              value={manifestPath}
              onChange={(event) => setManifestPath(event.target.value)}
              className="w-72 border-[var(--border)] bg-[var(--bg-base)]"
              aria-label={t('agents.import')}
            />
            <Button
              variant="subtle"
              size="md"
              onClick={handleImport}
              disabled={importing || !manifestPath.trim()}
            >
              {importing ? t('agents.importing') : t('agents.import')}
            </Button>
          </>
        }
      />

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
              {agents.map((agent) => (
                <TableRow key={agent.agent_id}>
                  <TableCell>
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
        </Card>
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
