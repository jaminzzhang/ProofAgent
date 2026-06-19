import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Search } from 'lucide-react'
import {
  Card,
  EmptyState,
  Input,
  OutcomeBadge,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  type ReceiptOutcome,
} from '@proofagent/ui'
import { useRuns } from '../hooks/useRuns'
import type { RunPurposeFilter } from '../api/types'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'

const OUTCOME_FILTERS: { value: ReceiptOutcome | 'all'; labelKey: string }[] = [
  { value: 'all', labelKey: 'runs.allOutcomes' },
  { value: 'ANSWERED_WITH_CITATIONS', labelKey: 'runs.answeredWithCitations' },
  { value: 'REFUSED_NO_EVIDENCE', labelKey: 'runs.refusedNoEvidence' },
  { value: 'WAITING_FOR_APPROVAL', labelKey: 'runs.waitingForApproval' },
  { value: 'TOOL_APPROVAL_DENIED', labelKey: 'runs.toolApprovalDenied' },
  { value: 'FAILED_WITH_TRACE', labelKey: 'runs.failed' },
]

const PURPOSE_FILTERS: { value: RunPurposeFilter; labelKey: string }[] = [
  { value: 'production', labelKey: 'common.production' },
  { value: 'validation', labelKey: 'common.validation' },
  { value: 'all', labelKey: 'common.allRuns' },
]

export function RunsListPage() {
  const [search, setSearch] = useState('')
  const [outcomeFilter, setOutcomeFilter] = useState<ReceiptOutcome | 'all'>('all')
  const [runPurpose, setRunPurpose] = useState<RunPurposeFilter>('production')
  const { t, formatDateTime, formatNumber } = useLocale()
  const { runs, total, loading } = useRuns(
    outcomeFilter === 'all' ? undefined : outcomeFilter,
    search || undefined,
    runPurpose,
  )

  return (
    <div className="max-w-7xl space-y-5">
      <PageHeader title={t('runs.title')} description={t('runs.description')} />

      {/* Toolbar: search + Radix Select filters */}
      <Card className="flex flex-wrap items-center gap-3 p-3">
        <div className="relative min-w-[220px] flex-1">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
          />
          <Input
            type="text"
            placeholder={t('runs.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="border-[var(--border)] bg-[var(--bg-base)] pl-9"
          />
        </div>

        <Select
          value={outcomeFilter}
          onValueChange={(v) => setOutcomeFilter(v as ReceiptOutcome | 'all')}
        >
          <SelectTrigger className="h-9 w-[200px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OUTCOME_FILTERS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {t(f.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={runPurpose}
          onValueChange={(v) => setRunPurpose(v as RunPurposeFilter)}
        >
          <SelectTrigger className="h-9 w-[160px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PURPOSE_FILTERS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {t(f.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Card>

      <div className="flex items-center justify-between px-1 text-sm text-[var(--text-muted)]">
        <span>
          {t('runs.showing')
            .replace('{shown}', formatNumber(runs.length))
            .replace('{total}', formatNumber(total))}
        </span>
      </div>

      {loading ? (
        <Card className="p-0">
          <TableSkeleton rows={6} columns={5} />
        </Card>
      ) : runs.length === 0 ? (
        <Card>
          <EmptyState message={t('runs.noMatches')} />
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <Table>
            <TableHeader>
              <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
                <TableHead>{t('common.runId')}</TableHead>
                <TableHead>{t('common.question')}</TableHead>
                <TableHead>{t('common.outcome')}</TableHead>
                <TableHead>{t('common.purpose')}</TableHead>
                <TableHead>{t('common.time')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.run_id}>
                  <TableCell className="font-mono text-xs">
                    <Link
                      to={`/runs/${run.run_id}`}
                      className="font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--accent)]"
                    >
                      {run.run_id}
                    </Link>
                  </TableCell>
                  <TableCell className="max-w-md truncate font-medium text-[var(--text-primary)]">
                    {run.question}
                  </TableCell>
                  <TableCell>
                    <OutcomeBadge outcome={run.outcome as ReceiptOutcome} t={t} />
                  </TableCell>
                  <TableCell className="text-xs font-medium capitalize text-[var(--text-secondary)]">
                    {run.run_purpose}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--text-muted)]">
                    {formatDateTime(run.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}
