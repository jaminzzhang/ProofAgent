import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Badge,
  Card,
  EmptyState,
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
} from '@proofagent/ui'
import type { ApprovalQueueItem, ApprovalStatusFilter } from '../api/types'
import { useApprovals } from '../hooks/useApprovals'
import { usePagination } from '../hooks/usePagination'
import { PaginationBar } from '../components/PaginationBar'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'

const PAGE_SIZE_OPTIONS = [25, 50, 100]
const STATUS_FILTERS: { value: ApprovalStatusFilter; labelKey: string }[] = [
  { value: 'pending', labelKey: 'approvals.pending' },
  { value: 'expired', labelKey: 'approvals.expired' },
  { value: 'all', labelKey: 'approvals.filterAll' },
]

export function ApprovalsPage() {
  const { t, formatNumber } = useLocale()

  // Status filter mirrors ?status (defaults to "pending" — triage view).
  const [searchParams, setSearchParams] = useSearchParams()
  const rawStatus = searchParams.get('status')
  const status: ApprovalStatusFilter =
    rawStatus === 'all' || rawStatus === 'expired' || rawStatus === 'pending'
      ? rawStatus
      : 'pending'

  const setStatus = (next: ApprovalStatusFilter) => {
    setSearchParams(
      (prev) => {
        const sp = new URLSearchParams(prev)
        if (next === 'pending') sp.delete('status')
        else sp.set('status', next)
        // changing status resets to page 1
        sp.delete('page')
        return sp
      },
      { replace: false },
    )
  }

  const [total, setTotal] = useState(0)
  const pagination = usePagination({ total, pageSizeOptions: PAGE_SIZE_OPTIONS })
  const { page, pageSize, offset, setPage } = pagination

  // One fetch with limit/offset: returns the page slice and the
  // status-scoped total (meta.total) so the pager stays consistent.
  const { approvals, total: fetchedTotal, loading, error } = useApprovals({
    status,
    limit: pageSize,
    offset,
  })

  // Mirror the status-scoped total into state for the pager (render N+1).
  useEffect(() => {
    setTotal(fetchedTotal)
  }, [fetchedTotal])

  // Reset to page 1 whenever the status filter changes.
  useEffect(() => {
    setPage(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  return (
    <div className="max-w-7xl space-y-5">
      <PageHeader
        title={t('approvals.title')}
        description={t('approvals.description')}
        actions={
          <Badge variant="subtle">
            {t('approvals.count')
              .replace('{shown}', formatNumber(approvals.length))
              .replace('{total}', formatNumber(total))}
          </Badge>
        }
      />

      <Card className="flex flex-wrap items-center gap-3 p-3">
        <Select value={status} onValueChange={(v) => setStatus(v as ApprovalStatusFilter)}>
          <SelectTrigger className="h-9 w-[200px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTERS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {t(f.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Card>

      {loading ? (
        <Card className="p-0">
          <TableSkeleton rows={5} columns={6} />
        </Card>
      ) : error ? (
        <Card>
          <EmptyState message={t('approvals.loadError')} />
        </Card>
      ) : approvals.length === 0 ? (
        <Card>
          <EmptyState message={t('approvals.empty')} />
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <Table>
            <TableHeader>
              <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
                <TableHead>{t('approvals.status')}</TableHead>
                <TableHead>{t('approvals.run')}</TableHead>
                <TableHead>{t('approvals.tool')}</TableHead>
                <TableHead>{t('common.question')}</TableHead>
                <TableHead>{t('approvals.parameters')}</TableHead>
                <TableHead>{t('approvals.expires')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {approvals.map((approval) => (
                <ApprovalRow key={`${approval.run_id}-${approval.approval_id}`} approval={approval} />
              ))}
            </TableBody>
          </Table>
          <div className="px-3">
            <PaginationBar
              page={page}
              pageSize={pageSize}
              totalPages={pagination.totalPages}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              shown={approvals.length}
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

function ApprovalRow({ approval }: { approval: ApprovalQueueItem }) {
  const { t, formatDateTime, formatNumber } = useLocale()

  return (
    <TableRow>
      <TableCell>
        <Badge variant={approval.expired ? 'danger' : 'warning'}>
          {approval.expired ? t('approvals.expired') : t('approvals.pending')}
        </Badge>
      </TableCell>
      <TableCell className="font-mono text-xs">
        <Link
          to={`/runs/${approval.run_id}#approval`}
          state={{ returnTo: '/approvals', returnLabel: t('approvals.back') }}
          className="text-[var(--text-secondary)] transition-colors hover:text-[var(--accent)]"
        >
          {approval.run_id}
        </Link>
        <div className="mt-1 text-[11px] text-[var(--text-muted)]">{approval.run_purpose}</div>
      </TableCell>
      <TableCell>
        <div className="font-mono text-xs text-[var(--text-primary)]">{approval.tool_name}</div>
        <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">{approval.approval_id}</div>
      </TableCell>
      <TableCell className="max-w-sm text-[var(--text-primary)]">
        <div className="truncate font-medium">{approval.question}</div>
        <div className="mt-1 text-xs text-[var(--text-muted)]">{approval.agent_id ?? t('approvals.unknownAgent')}</div>
      </TableCell>
      <TableCell className="text-xs text-[var(--text-secondary)]">
        <div className="font-mono">{parameterKeySummary(approval.parameter_keys, t)}</div>
        <div className="mt-1 text-[var(--text-muted)]">
          {formatNumber(approval.parameter_count)}{' '}
          {approval.parameter_count === 1 ? t('approvals.parameter') : t('approvals.parametersCount')}
        </div>
      </TableCell>
      <TableCell className="font-mono text-xs text-[var(--text-muted)]">
        {formatDateTime(approval.expires_at)}
      </TableCell>
    </TableRow>
  )
}

function parameterKeySummary(keys: string[], t: (key: string, fallback?: string) => string): string {
  return keys.length ? keys.join(', ') : t('approvals.none')
}
