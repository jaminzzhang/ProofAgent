import { useEffect, useState } from 'react'
import { fetchKnowledgeOperations } from '../../api/client'
import type { KnowledgeOperationsProjection } from '../../api/types'
import { LoadingSpinner } from '../ui/LoadingSpinner'

export function KnowledgeOperationsPanel({ sourceId }: { sourceId: string }) {
  const [projection, setProjection] = useState<KnowledgeOperationsProjection | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setProjection(null)
    setError(null)
    fetchKnowledgeOperations(sourceId)
      .then((value) => {
        if (!cancelled) setProjection(value)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : 'Unable to load Knowledge operations.')
        }
      })
    return () => { cancelled = true }
  }, [sourceId])

  return (
    <section
      aria-labelledby="knowledge-operations-heading"
      className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5"
    >
      <div>
        <h3 id="knowledge-operations-heading" className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Knowledge operations
        </h3>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Trace-safe Hybrid health, release blockers, and capacity diagnostics.
        </p>
      </div>

      {!projection && !error ? <div className="flex justify-center py-8" role="status"><LoadingSpinner /></div> : null}
      {error ? <p role="alert" className="mt-4 text-sm text-[var(--danger)]">{error}</p> : null}
      {projection ? <OperationsBody projection={projection} /> : null}
    </section>
  )
}

function OperationsBody({ projection }: { projection: KnowledgeOperationsProjection }) {
  return (
    <div className="mt-5 space-y-5">
      <div>
        <h4 className="text-sm font-semibold text-[var(--text-primary)]">Release blockers</h4>
        {!projection.telemetry_complete ? (
          <p className="mt-2 text-sm text-[var(--danger)]">Telemetry is incomplete; release remains blocked.</p>
        ) : null}
        <div className="mt-3 grid gap-2 text-sm md:grid-cols-2 xl:grid-cols-3">
          <Fact label="Unauthorized candidates" value={projection.unauthorized_candidate_exposure} />
          <Fact label="Wrong version or precedence" value={projection.wrong_version_or_precedence} />
          <Fact label="Unresolvable citations" value={projection.unresolvable_formal_citation} />
          <Fact label="Advice under authority uncertainty" value={projection.advice_under_authority_uncertainty} />
          <Fact label="High-severity unsupported claims" value={projection.high_severity_unsupported_claim} />
          <Fact label="Citation failures" value={projection.citation_failure_count} />
        </div>
      </div>

      <div>
        <h4 className="text-sm font-semibold text-[var(--text-primary)]">Backlog and throughput</h4>
        <div className="mt-3 grid gap-2 text-sm md:grid-cols-2 xl:grid-cols-3">
          <Fact label="Review backlog" value={projection.review_backlog} />
          <Fact label="Retry backlog" value={projection.retry_backlog} />
          <Fact label="Embedding backlog" value={projection.embedding_backlog} />
          <Fact label="Parser escalations" value={projection.parser_escalation_count} />
          <Fact label="Orphans" value={projection.orphan_count} />
          <Fact label="Documents / hour" value={projection.ingestion_throughput_documents_per_hour} />
          <Fact label="Oldest queue item seconds" value={projection.queue_age_seconds} />
          <Fact label="GPU queue depth" value={projection.gpu_queue_depth} />
          <Fact label="Index lag seconds" value={projection.index_lag_seconds} />
          <Fact label="Publication age seconds" value={projection.publication_age_seconds ?? 'unavailable'} />
          <Fact label="Rebuild state" value={projection.rebuild_state} />
        </div>
      </div>

      <div>
        <h4 className="text-sm font-semibold text-[var(--text-primary)]">Latency and outcomes</h4>
        <div className="mt-3 grid gap-2 text-sm md:grid-cols-2 xl:grid-cols-3">
          <Fact label="Retrieval P95 ms" value={projection.retrieval_p95_ms} />
          <Fact label="Scheduler queue P95 ms" value={projection.scheduler_queue_p95_ms} />
          <Fact label="GPU utilization %" value={projection.gpu_utilization_percent} />
          <Fact label="No evidence rate" value={formatRate(projection.no_evidence_rate)} />
          <Fact label="Clarification rate" value={formatRate(projection.clarification_rate)} />
          <Fact label="Conflict rate" value={formatRate(projection.conflict_rate)} />
          <Fact label="Refusal rate" value={formatRate(projection.refusal_rate)} />
          <Fact label="Degradation rate" value={formatRate(projection.degradation_rate)} />
          <Fact label="Slot coverage" value={formatRate(projection.complete_evidence_slot_coverage_rate)} />
          {projection.stage_latencies.map((item) => (
            <Fact key={item.stage} label={`${item.stage} P95 ms`} value={item.p95_ms} />
          ))}
        </div>
      </div>
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-[var(--text-secondary)]">
      {label}: <span className="font-mono text-[var(--text-primary)]">{value}</span>
    </div>
  )
}

function formatRate(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}
