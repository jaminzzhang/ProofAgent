import { Badge, Card, EmptyState } from '@proofagent/ui'
import type { EvidenceChunk } from '../../api/types'

interface EvidenceTabProps {
  chunks: EvidenceChunk[]
}

export function EvidenceTab({ chunks }: EvidenceTabProps) {
  if (chunks.length === 0) return <EmptyState message="No evidence data available." />

  const accepted = chunks.filter((c) => c.status === 'accepted').length

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-muted)]">
        {accepted}/{chunks.length} accepted
      </p>
      {chunks.map((chunk) => {
        const admissionScore = chunk.admission_score ?? chunk.score ?? null
        const isAccepted = chunk.status === 'accepted'
        return (
          <Card
            key={chunk.index}
            className={`p-4 ${
              isAccepted
                ? 'border-[var(--success-border)] bg-[var(--success-bg)]'
                : 'border-[var(--danger-border)] bg-[var(--danger-bg)]'
            }`}
          >
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge variant={isAccepted ? 'success' : 'danger'}>
                {isAccepted ? 'Accepted' : 'Rejected'}
              </Badge>
              {admissionScore !== null && (
                <span className="text-xs text-[var(--text-muted)]">
                  Admission: {admissionScore.toFixed(2)}
                </span>
              )}
              {chunk.provider_native_score !== null &&
                chunk.provider_native_score !== undefined && (
                  <span className="text-xs text-[var(--text-muted)]">
                    Native: {chunk.provider_native_score.toFixed(2)}
                  </span>
                )}
              {chunk.fusion_rank !== null && chunk.fusion_rank !== undefined && (
                <span className="text-xs text-[var(--text-muted)]">
                  Rank: {chunk.fusion_rank}
                </span>
              )}
              {chunk.source_id && (
                <span className="rounded bg-[var(--bg-base)] px-1.5 py-0.5 font-mono text-xs text-[var(--text-secondary)]">
                  {chunk.source_id}
                </span>
              )}
              {chunk.binding_id && (
                <span className="rounded bg-[var(--bg-base)] px-1.5 py-0.5 font-mono text-xs text-[var(--text-secondary)]">
                  {chunk.binding_id}
                </span>
              )}
            </div>
            <p className="mb-1 font-mono text-xs text-[var(--text-muted)]">
              {chunk.citation ?? chunk.source}
            </p>
          </Card>
        )
      })}
    </div>
  )
}
