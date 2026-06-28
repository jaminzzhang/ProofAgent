import { useEffect, useState } from 'react'
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
import { usePagination } from '../hooks/usePagination'
import { PaginationBar } from '../components/PaginationBar'
import type { RunPurposeFilter } from '../api/types'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'

const PAGE_SIZE_OPTIONS = [25, 50, 100]

/** Debounce a fast-changing value (e.g. a search box) by `delayMs`. */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(id)
  }, [value, delayMs])
  return debounced
}

const OUTCOME_FILTERS: { value: ReceiptOutcome | 'all'; labelKey: string }[] = [
  { value: 'all', labelKey: 'runs.allOutcomes' },
  { value: 'ANSWERED_WITH_CITATIONS', labelKey: 'runs.answeredWithCitations' },
  { value: 'REFUSED_NO_EVIDENCE', labelKey: 'runs.refusedNoEvidence' },
  { value: 'WAITING_FOR_APPROVAL', labelKey: 'runs.waitingForApproval' },
  { value: 'TOOL_APPROVAL_DENIED', labelKey: 'runs.toolApprovalDenied' },
  { value: 'POLICY_DENIED', labelKey: 'runs.policyDenied' },
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
  // Persisted filtered total so the pager knows the page count before the
  // next fetch resolves.
  const [total, setTotal] = useState(0)
  const { t, formatDateTime } = useLocale()

  // Debounce the search so fast typing does not fire a request per keystroke.
  const debouncedSearch = useDebouncedValue(search, 300)

  // The values that, when changed, reset the list back to page 1.
  const outcomeParam = outcomeFilter === 'all' ? undefined : outcomeFilter
  const searchParam = debouncedSearch || undefined

  const pagination = usePagination({ total, pageSizeOptions: PAGE_SIZE_OPTIONS })
  const { page, pageSize, offset, setPage } = pagination

  // One fetch with limit/offset: returns both the page slice and the
  // filtered total (meta.total) so the pager's page count stays correct.
  const { runs, total: fetchedTotal, loading } = useRuns({
    outcome: outcomeParam,
    search: searchParam,
    runPurpose,
    limit: pageSize,
    offset,
  })

  // Mirror the filtered total into state for the pager (render N+1).
  useEffect(() => {
    setTotal(fetchedTotal)
  }, [fetchedTotal])

  // Reset to page 1 whenever a content filter changes.
  useEffect(() => {
    setPage(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outcomeParam, searchParam, runPurpose])

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
          <div className="px-3">
            <PaginationBar
              page={page}
              pageSize={pageSize}
              totalPages={pagination.totalPages}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              shown={runs.length}
              total={total}
              onPageChange={setPage}
              onPageSizeChange={pagination.setPageSize}
            />
          </div>
        </Card>
      )}
    </div>
  )
}
