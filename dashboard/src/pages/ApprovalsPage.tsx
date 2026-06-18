import { Link } from 'react-router-dom'
import type { ApprovalQueueItem } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useApprovals } from '../hooks/useApprovals'
import { useLocale } from '../i18n/locale'

export function ApprovalsPage() {
  const { approvals, total, loading, error } = useApprovals()
  const { t, formatNumber } = useLocale()

  return (
    <div className="max-w-6xl space-y-6">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">{t('approvals.title')}</h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">{t('approvals.description')}</p>
        </div>
        <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-secondary)]">
          {t('approvals.count').replace('{shown}', formatNumber(approvals.length)).replace('{total}', formatNumber(total))}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><LoadingSpinner /></div>
      ) : error ? (
        <EmptyState message={t('approvals.loadError')} />
      ) : approvals.length === 0 ? (
        <EmptyState message={t('approvals.empty')} />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('approvals.status')}</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('approvals.run')}</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('approvals.tool')}</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('common.question')}</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('approvals.parameters')}</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('approvals.expires')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {approvals.map((approval) => (
                <ApprovalRow key={`${approval.run_id}-${approval.approval_id}`} approval={approval} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ApprovalRow({ approval }: { approval: ApprovalQueueItem }) {
  const { t, formatDateTime, formatNumber } = useLocale()

  return (
    <tr className="group hover:bg-[var(--bg-hover)]">
      <td className="px-5 py-3">
        <span className={`rounded-md px-2 py-1 text-xs font-semibold ${approval.expired ? 'bg-[var(--danger)]/10 text-[var(--danger)]' : 'bg-[var(--warning-bg)] text-[var(--warning)]'}`}>
          {approval.expired ? t('approvals.expired') : t('approvals.pending')}
        </span>
      </td>
      <td className="px-5 py-3 font-mono text-xs">
        <Link
          to={`/runs/${approval.run_id}#approval`}
          state={{ returnTo: '/approvals', returnLabel: t('approvals.back') }}
          className="text-[var(--text-secondary)] transition-colors group-hover:text-[var(--accent)]"
        >
          {approval.run_id}
        </Link>
        <div className="mt-1 text-[11px] text-[var(--text-muted)]">{approval.run_purpose}</div>
      </td>
      <td className="px-5 py-3">
        <div className="font-mono text-xs text-[var(--text-primary)]">{approval.tool_name}</div>
        <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">{approval.approval_id}</div>
      </td>
      <td className="max-w-sm px-5 py-3 text-[var(--text-primary)]">
        <div className="truncate font-medium">{approval.question}</div>
        <div className="mt-1 text-xs text-[var(--text-muted)]">{approval.agent_id ?? t('approvals.unknownAgent')}</div>
      </td>
      <td className="px-5 py-3 text-xs text-[var(--text-secondary)]">
        <div className="font-mono">{parameterKeySummary(approval.parameter_keys, t)}</div>
        <div className="mt-1 text-[var(--text-muted)]">{formatNumber(approval.parameter_count)} {approval.parameter_count === 1 ? t('approvals.parameter') : t('approvals.parametersCount')}</div>
      </td>
      <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{formatDateTime(approval.expires_at)}</td>
    </tr>
  )
}

function parameterKeySummary(keys: string[], t: (key: string, fallback?: string) => string): string {
  return keys.length ? keys.join(', ') : t('approvals.none')
}
