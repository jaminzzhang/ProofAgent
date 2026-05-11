import { useState, useEffect } from 'react'
import { fetchStats } from '../api/client'
import type { StatsResponse } from '../api/types'

interface UseStatsResult {
  stats: StatsResponse | null
  loading: boolean
  error: string | null
}

export function useStats(): UseStatsResult {
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  return { stats, loading, error }
}
