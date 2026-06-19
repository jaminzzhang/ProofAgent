import { Link } from 'react-router-dom'
import {
  Badge,
  Card,
  EmptyState,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@proofagent/ui'
import type { ApprovalQueueItem } from '../api/types'
import { useApprovals } from '../hooks/useApprovals'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'

export function ApprovalsPage() {
  const { approvals, total, loading, error } = useApprovals()
  const { t, formatNumber } = useLocale()

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
