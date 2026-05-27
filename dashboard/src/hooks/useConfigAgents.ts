import { useEffect, useState } from 'react'
import { fetchConfigAgents } from '../api/client'
import type { ConfigAgentSummary } from '../api/types'

interface UseConfigAgentsResult {
  agents: ConfigAgentSummary[]
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useConfigAgents(): UseConfigAgentsResult {
  const [agents, setAgents] = useState<ConfigAgentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchConfigAgents()
      .then((data) => setAgents(data.data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [refreshToken])

  return {
    agents,
    loading,
    error,
    refresh: () => setRefreshToken((value) => value + 1),
  }
}
