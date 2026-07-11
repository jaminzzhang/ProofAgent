import { Badge, Card, EmptyState } from '@proofagent/ui'
import type { EvidenceChunk } from '../../api/types'

interface EvidenceTabProps {
  chunks: EvidenceChunk[]
}

function legacyEvidenceScore(chunk: EvidenceChunk): number | null {
  const score = (chunk as { score?: unknown }).score
  return typeof score === 'number' && Number.isFinite(score) ? score : null
}

function evidenceKeySeed(chunk: EvidenceChunk): string {
  const runtimeIndex = (chunk as { index?: unknown }).index
  if (
    typeof runtimeIndex === 'number' &&
    Number.isSafeInteger(runtimeIndex) &&
    runtimeIndex >= 0
  ) {
    return JSON.stringify(['index', runtimeIndex])
  }

  return JSON.stringify([
    'legacy',
    chunk.source_id ?? null,
    chunk.binding_id ?? null,
    chunk.citation ?? null,
    chunk.source ?? null,
    chunk.status,
    chunk.admission_score ?? null,
    legacyEvidenceScore(chunk),
    chunk.provider_native_score ?? null,
    chunk.fusion_rank ?? null,
  ])
}

function keyEvidenceChunks(chunks: EvidenceChunk[]) {
  const duplicateCounts = new Map<string, number>()
  return chunks.map((chunk) => {
    const seed = evidenceKeySeed(chunk)
    const duplicateOrdinal = duplicateCounts.get(seed) ?? 0
    duplicateCounts.set(seed, duplicateOrdinal + 1)
    return { chunk, key: JSON.stringify([seed, duplicateOrdinal]) }
  })
}

export function EvidenceTab({ chunks }: EvidenceTabProps) {
  if (chunks.length === 0) return <EmptyState message="No evidence data available." />

  const accepted = chunks.filter((c) => c.status === 'accepted').length

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-muted)]">
        {accepted}/{chunks.length} accepted
      </p>
      {keyEvidenceChunks(chunks).map(({ chunk, key }) => {
        const admissionScore = chunk.admission_score ?? legacyEvidenceScore(chunk)
        const isAccepted = chunk.status === 'accepted'
        return (
          <Card
            key={key}
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
