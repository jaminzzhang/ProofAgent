import { useState, useEffect } from 'react'
import { fetchRuns } from '../api/client'
import type { RunPurposeFilter, RunSummary, ReceiptOutcome } from '../api/types'

interface UseRunsResult {
  runs: RunSummary[]
  total: number
  loading: boolean
  error: string | null
}

export function useRuns(params: {
  outcome?: ReceiptOutcome
  search?: string
  runPurpose?: RunPurposeFilter
  limit?: number
  offset?: number
}): UseRunsResult {
  const { outcome, search, runPurpose, limit, offset } = params
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchRuns({ outcome, search, run_purpose: runPurpose, limit, offset })
      .then((data) => {
        setRuns(data.data)
        setTotal(data.meta.total)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [outcome, search, runPurpose, limit, offset])

  return { runs, total, loading, error }
}
