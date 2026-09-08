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
    let active = true
    setLoading(true)
    setError(null)
    // Bracket the separate Contract read with monotonically increasing Draft revisions.
    // Concurrent writes must never pair older content with a newer CAS token.
    async function loadSnapshot() {
      for (let attempt = 0; attempt < 2; attempt++) {
        const before = await fetchConfigDraft(agentId!, draftId!)
        if (!active) return
        const contractData = await fetchConfigDraftContract(agentId!, draftId!)
        if (!active) return
        const after = await fetchConfigDraft(agentId!, draftId!)
        if (!active) return
        if (typeof before.revision === 'number' && before.revision === after.revision) {
          setDraft(after)
          setContract(contractData)
          return
        }
      }
      throw new Error('agent_draft_snapshot_changed_retry')
    }
    loadSnapshot()
      .catch((err) => {
        if (!active) return
        setDraft(null)
        setContract(null)
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [agentId, draftId, refreshToken])

  return {
    draft,
    contract,
    loading,
    error,
    refresh: () => setRefreshToken((value) => value + 1),
  }
}
