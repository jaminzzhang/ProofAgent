import { useCallback, useState, useEffect } from 'react'
import { fetchRunDetail } from '../api/client'
import type { RunDetail } from '../api/types'

interface UseRunDetailResult {
  detail: RunDetail | null
  loading: boolean
  error: string | null
  refetch: () => Promise<void>
}

export function useRunDetail(runId: string | undefined): UseRunDetailResult {
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!runId) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const nextDetail = await fetchRunDetail(runId)
      setDetail(nextDetail)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [runId])

  useEffect(() => {
    void load()
  }, [load])

  return { detail, loading, error, refetch: load }
}
