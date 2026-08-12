import { useEffect, useState } from 'react'
import { fetchConfigAgents } from '../api/client'
import type { AgentConfigurationCapabilities, ConfigAgentSummary } from '../api/types'

interface UseConfigAgentsResult {
  agents: ConfigAgentSummary[]
  loading: boolean
  error: string | null
  capabilities: AgentConfigurationCapabilities | null
  refresh: () => void
}

export function useConfigAgents(): UseConfigAgentsResult {
  const [agents, setAgents] = useState<ConfigAgentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [capabilities, setCapabilities] = useState<AgentConfigurationCapabilities | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchConfigAgents()
      .then((data) => {
        setAgents(data.data)
        setCapabilities(data.meta.capabilities)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [refreshToken])

  return {
    agents,
    loading,
    error,
    capabilities,
    refresh: () => setRefreshToken((value) => value + 1),
  }
}
