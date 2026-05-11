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
      {chunks.map((chunk) => (
        <div
          key={chunk.index}
          className={`border rounded-lg p-4 ${
            chunk.status === 'accepted'
              ? 'border-green-500/20 bg-green-500/5'
              : 'border-red-500/20 bg-red-500/5'
          }`}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-xs font-medium ${chunk.status === 'accepted' ? 'text-green-400' : 'text-red-400'}`}>
              {chunk.status === 'accepted' ? 'Accepted' : 'Rejected'}
            </span>
            {chunk.score !== null && (
              <span className="text-xs text-[var(--text-muted)]">Score: {chunk.score.toFixed(2)}</span>
            )}
          </div>
          <p className="text-xs font-mono text-[var(--text-muted)] mb-1">{chunk.source}</p>
        </div>
      ))}
    </div>
  )
}
