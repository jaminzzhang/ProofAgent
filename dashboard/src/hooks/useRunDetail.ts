import { useState, useEffect } from 'react'
import { fetchRunDetail } from '../api/client'
import type { RunDetail } from '../api/types'

interface UseRunDetailResult {
  detail: RunDetail | null
  loading: boolean
  error: string | null
}

export function useRunDetail(runId: string | undefined): UseRunDetailResult {
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!runId) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    fetchRunDetail(runId)
      .then(setDetail)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [runId])

  return { detail, loading, error }
}
