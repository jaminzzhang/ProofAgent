// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchKnowledgeOperations } from '../../../api/client'
import { KnowledgeOperationsPanel } from '../KnowledgeOperationsPanel'

vi.mock('../../../api/client', () => ({ fetchKnowledgeOperations: vi.fn() }))

describe('KnowledgeOperationsPanel', () => {
  beforeEach(() => {
    vi.mocked(fetchKnowledgeOperations).mockResolvedValue({
      source_id: 'ks_1', telemetry_complete: true, queue_age_seconds: 15,
      retry_backlog: 3, review_backlog: 12, parser_escalation_count: 2,
      ingestion_throughput_documents_per_hour: 44, gpu_queue_depth: 4,
      gpu_utilization_percent: 73, embedding_backlog: 9, index_lag_seconds: 21,
      orphan_count: 0, publication_age_seconds: 3600, rebuild_state: 'idle',
      scheduler_queue_p95_ms: 120, retrieval_service_p95_ms: 380,
      retrieval_p95_ms: 500, stage_latencies: [], no_evidence_rate: 0.03,
      clarification_rate: 0.08, conflict_rate: 0.01, refusal_rate: 0.02,
      degradation_rate: 0, citation_failure_count: 0,
      complete_evidence_slot_coverage_rate: 0.94,
      unauthorized_candidate_exposure: 0, wrong_version_or_precedence: 0,
      unresolvable_formal_citation: 0, advice_under_authority_uncertainty: 0,
      high_severity_unsupported_claim: 0, release_blocker_count: 0,
    })
  })

  it('shows release blockers before throughput diagnostics', async () => {
    render(<KnowledgeOperationsPanel sourceId="ks_1" />)

    const blockers = await screen.findByText('Release blockers')
    expect(screen.getByText('Unauthorized candidates:', { exact: false })).toHaveTextContent('Unauthorized candidates: 0')
    expect(screen.getByText('Review backlog:', { exact: false })).toHaveTextContent('Review backlog: 12')
    const throughput = screen.getByText('Backlog and throughput')
    expect(blockers.compareDocumentPosition(throughput) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
