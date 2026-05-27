import { useEffect, useState } from 'react'
import { fetchConfigVersions } from '../api/client'
import type { PublishedAgentVersion } from '../api/types'

interface UseConfigVersionsResult {
  versions: PublishedAgentVersion[]
  activeVersionId: string | null
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useConfigVersions(agentId: string | undefined): UseConfigVersionsResult {
  const [versions, setVersions] = useState<PublishedAgentVersion[]>([])
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null)
  const [loading, setLoading] = useState(Boolean(agentId))
  const [error, setError] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    if (!agentId) {
      setVersions([])
      setActiveVersionId(null)
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    fetchConfigVersions(agentId)
      .then((data) => {
        setVersions(data.data)
        setActiveVersionId(data.meta.active_version_id)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [agentId, refreshToken])

  return {
    versions,
    activeVersionId,
    loading,
    error,
    refresh: () => setRefreshToken((value) => value + 1),
  }
}
