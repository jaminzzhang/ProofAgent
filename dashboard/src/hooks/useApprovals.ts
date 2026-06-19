import { useEffect, useState } from 'react'
import { fetchApprovals } from '../api/client'
import type { ApprovalQueueItem, ApprovalStatusFilter } from '../api/types'

interface UseApprovalsResult {
  approvals: ApprovalQueueItem[]
  total: number
  loading: boolean
  error: string | null
}

export function useApprovals(params: {
  status?: ApprovalStatusFilter
  limit?: number
  offset?: number
} = {}): UseApprovalsResult {
  const { status, limit, offset } = params
  const [approvals, setApprovals] = useState<ApprovalQueueItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchApprovals({ status, limit, offset })
      .then((response) => {
        setApprovals(response.data)
        setTotal(response.meta.total)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Unable to load approvals.'))
      .finally(() => setLoading(false))
  }, [status, limit, offset])

  return { approvals, total, loading, error }
}
