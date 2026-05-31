import type { EvidenceChunk } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'

interface EvidenceTabProps {
  chunks: EvidenceChunk[]
}

export function EvidenceTab({ chunks }: EvidenceTabProps) {
  if (chunks.length === 0) return <EmptyState message="No evidence data available." />

  const accepted = chunks.filter((c) => c.status === 'accepted').length

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-muted)]">{accepted}/{chunks.length} accepted</p>
      {chunks.map((chunk) => {
        const admissionScore = chunk.admission_score ?? chunk.score ?? null
        return (
          <div
            key={chunk.index}
            className={`border rounded-lg p-4 ${
              chunk.status === 'accepted'
                ? 'border-green-500/20 bg-green-500/5'
                : 'border-red-500/20 bg-red-500/5'
            }`}
          >
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className={`text-xs font-medium ${chunk.status === 'accepted' ? 'text-green-400' : 'text-red-400'}`}>
                {chunk.status === 'accepted' ? 'Accepted' : 'Rejected'}
              </span>
              {admissionScore !== null && (
                <span className="text-xs text-[var(--text-muted)]">Admission: {admissionScore.toFixed(2)}</span>
              )}
              {chunk.provider_native_score !== null && chunk.provider_native_score !== undefined && (
                <span className="text-xs text-[var(--text-muted)]">Native: {chunk.provider_native_score.toFixed(2)}</span>
              )}
              {chunk.fusion_rank !== null && chunk.fusion_rank !== undefined && (
                <span className="text-xs text-[var(--text-muted)]">Rank: {chunk.fusion_rank}</span>
              )}
              {chunk.source_id && (
                <span className="rounded bg-[var(--bg-base)] px-1.5 py-0.5 text-xs font-mono text-[var(--text-secondary)]">{chunk.source_id}</span>
              )}
              {chunk.binding_id && (
                <span className="rounded bg-[var(--bg-base)] px-1.5 py-0.5 text-xs font-mono text-[var(--text-secondary)]">{chunk.binding_id}</span>
              )}
            </div>
            <p className="text-xs font-mono text-[var(--text-muted)] mb-1">{chunk.citation ?? chunk.source}</p>
          </div>
        )
      })}
    </div>
  )
}
