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
    let active = true
    setLoading(true)
    setVersions([])
    setActiveVersionId(null)
    setError(null)
    fetchConfigVersions(agentId)
      .then((data) => {
        if (!active) return
        setVersions(data.data)
        setActiveVersionId(data.meta.active_version_id)
      })
      .catch((err) => { if (active) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [agentId, refreshToken])

  return {
    versions,
    activeVersionId,
    loading,
    error,
    refresh: () => setRefreshToken((value) => value + 1),
  }
}
