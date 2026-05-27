import { useEffect, useState } from 'react'
import { fetchConfigDraft, fetchConfigDraftContract } from '../api/client'
import type { ContractBundle, DraftAgent } from '../api/types'

interface UseConfigDraftResult {
  draft: DraftAgent | null
  contract: ContractBundle | null
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useConfigDraft(
  agentId: string | undefined,
  draftId: string | undefined,
): UseConfigDraftResult {
  const [draft, setDraft] = useState<DraftAgent | null>(null)
  const [contract, setContract] = useState<ContractBundle | null>(null)
  const [loading, setLoading] = useState(Boolean(agentId && draftId))
  const [error, setError] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    if (!agentId || !draftId) {
      setDraft(null)
      setContract(null)
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    Promise.all([
      fetchConfigDraft(agentId, draftId),
      fetchConfigDraftContract(agentId, draftId),
    ])
      .then(([draftData, contractData]) => {
        setDraft(draftData)
        setContract(contractData)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [agentId, draftId, refreshToken])

  return {
    draft,
    contract,
    loading,
    error,
    refresh: () => setRefreshToken((value) => value + 1),
  }
}
