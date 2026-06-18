import { useEffect, useState } from 'react'
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
import { fetchHandoffs } from '../api/client'
import type { HandoffProjection } from '../api/types'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'

export function HandoffsPage() {
  const [handoffs, setHandoffs] = useState<HandoffProjection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { t, formatDateTime } = useLocale()

  useEffect(() => {
    fetchHandoffs()
      .then((response) => {
        setHandoffs(response.data)
        setError(null)
      })
      .catch((err) => {
        console.error('Failed to fetch handoffs', err)
        setError(t('handoffs.loadError'))
      })
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="max-w-6xl space-y-5">
      <PageHeader title={t('handoffs.title')} description={t('handoffs.description')} />

      {loading ? (
        <Card className="p-0">
          <TableSkeleton rows={5} columns={5} />
        </Card>
      ) : error ? (
        <Card>
          <EmptyState message={error} />
        </Card>
      ) : handoffs.length === 0 ? (
        <Card>
          <EmptyState message={t('handoffs.empty')} />
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <Table>
            <TableHeader>
              <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
                <TableHead>{t('handoffs.reason')}</TableHead>
                <TableHead>{t('handoffs.customer')}</TableHead>
                <TableHead>{t('handoffs.summary')}</TableHead>
                <TableHead>{t('common.time')}</TableHead>
                <TableHead>{t('approvals.run')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {handoffs.map((handoff) => (
                <TableRow key={`${handoff.run_id}-${handoff.handoff_id || handoff.created_at}`}>
                  <TableCell>
                    <Badge variant="warning">{formatReason(handoff.reason)}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--text-secondary)]">
                    {handoff.customer_ref || t('handoffs.anonymous')}
                  </TableCell>
                  <TableCell className="max-w-xl">
                    <div className="truncate font-medium text-[var(--text-primary)]">
                      {handoff.question_summary || handoff.summary}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--text-muted)]">
                    {formatDateTime(handoff.created_at)}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    <Link
                      to={`/runs/${handoff.run_id}`}
                      className="text-[var(--accent)] hover:underline"
                    >
                      {handoff.run_id}
                    </Link>
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

function formatReason(reason: string) {
  return reason.replaceAll('_', ' ')
}
