// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import {
  fetchEvaluationCampaign,
  fetchEvaluationCampaignCases,
  fetchEvaluationCampaigns,
  fetchEvaluationCampaignTrends,
  fetchEvaluationProductionSampleCandidates,
  fetchEvaluationProductionSamplePromotions,
} from '../../api/client'
import type { EvaluationCampaignSummary } from '../../api/types'
import { AppRoutes } from '../../router'

vi.mock('../../api/client', () => ({
  fetchEvaluationCampaigns: vi.fn(),
  fetchEvaluationCampaign: vi.fn(),
  fetchEvaluationCampaignCases: vi.fn(),
  fetchEvaluationCampaignTrends: vi.fn(),
  fetchEvaluationProductionSampleCandidates: vi.fn(),
  fetchEvaluationProductionSamplePromotions: vi.fn(),
}))

describe('EvaluationLabPage', () => {
  it('renders campaign readiness and capability coverage on the hidden route', async () => {
    const campaign = evaluationCampaign()
    vi.mocked(fetchEvaluationCampaigns).mockResolvedValue({
      data: [campaign],
      meta: { total: 1 },
    })
    vi.mocked(fetchEvaluationCampaign).mockResolvedValue(campaign)
    vi.mocked(fetchEvaluationCampaignCases).mockResolvedValue({
      campaign_id: 'active_agent_probe',
      data: [
        {
          analysis_id: 'active_agent_smoke-active_agent_subjects',
          suite_id: 'active_agent_smoke',
          suite_version: '2026-06-21',
          case_id: 'supported',
          status: 'passed',
          expected_outcome: 'ANSWERED_WITH_CITATIONS',
          actual_outcome: 'ANSWERED_WITH_CITATIONS',
          artifact_sufficiency: 'sufficient',
          primary_failure_owner: null,
          response_projection: {
            audience: 'operator',
            text_length: 18,
          },
          gate_failures: [],
          diagnostic_findings: [],
          diagnostic_blocker_candidate: false,
        },
      ],
      meta: { total: 1 },
    })
    vi.mocked(fetchEvaluationCampaignTrends).mockResolvedValue({
      campaign_id: 'active_agent_probe',
      current_version: '2026-06-21',
      baseline_campaign_id: 'previous_probe',
      baseline_version: '2026-06-20',
      status: 'comparable',
      comparison_basis: {
        target_agent_id: 'insurance_customer_service',
        current_target_agent_version_id: 'published_v1',
        baseline_target_agent_version_id: 'published_v0',
        suite_versions: [],
      },
      metric_deltas: {
        governed_resolution_rate: 0.5,
        artifact_sufficiency_rate: 0,
        deterministic_gate_pass_rate: 0,
      },
    })
    vi.mocked(fetchEvaluationProductionSampleCandidates).mockResolvedValue({
      data: [
        {
          batch_id: 'prod_edge_cases',
          batch_dir: '/tmp/curation/prod_edge_cases',
          sample_id: 'prod_supported',
          source_run_id: 'run_prod_supported',
          curation_status: 'diagnostic_only',
          formal_scoring_allowed: false,
          run_purpose: 'production',
          safe_summary: {
            question_sha256: 'question-hash',
            question_text_length: 42,
            response_text_sha256: 'response-hash',
            response_text_length: 28,
          },
        },
      ],
      meta: { total: 1 },
    })
    vi.mocked(fetchEvaluationProductionSamplePromotions).mockResolvedValue({
      data: [
        {
          promotion_dir: '/tmp/curation/promoted/prod_supported',
          promotion_record_path:
            '/tmp/curation/promoted/prod_supported/production_sample_promotion.json',
          sample_id: 'prod_supported',
          status: 'promoted',
          source_run_id: 'run_prod_supported',
          suite_path: 'evaluation_suite.yaml',
          subject_manifest_path: 'evaluation_subjects.yaml',
          domain_review: {
            reviewer: 'domain-reviewer',
            confirmed: true,
          },
          harness_review: {
            reviewer: 'harness-reviewer',
            confirmed: true,
          },
        },
      ],
      meta: { total: 1 },
    })

    render(
      <MemoryRouter initialEntries={['/evaluation-lab']}>
        <AppRoutes />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: 'Evaluation Lab' })).toBeInTheDocument()
    expect(await screen.findByText('active_agent_probe')).toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(screen.getByText('Trend vs previous_probe')).toBeInTheDocument()
    expect(screen.getByText('+50%')).toBeInTheDocument()
    expect(screen.getByText('Intelligent Resolution')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('0 blocker candidates')).toBeInTheDocument()
    expect(screen.getByText('Evidence Answer')).toBeInTheDocument()
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(await screen.findByText('Case Drilldowns')).toBeInTheDocument()
    expect(screen.getByText('supported')).toBeInTheDocument()
    expect(screen.getByText('ANSWERED_WITH_CITATIONS')).toBeInTheDocument()
    expect(await screen.findByText('Production Sample Curation')).toBeInTheDocument()
    expect(screen.getByText('1 diagnostic candidates')).toBeInTheDocument()
    expect(screen.getByText('1 promoted samples')).toBeInTheDocument()
    expect(screen.getByText('prod_supported')).toBeInTheDocument()
    expect(screen.getByText('prod_edge_cases')).toBeInTheDocument()
  })
})

function evaluationCampaign(): EvaluationCampaignSummary {
  return {
    campaign_id: 'active_agent_probe',
    version: '2026-06-21',
    target_agent_id: 'insurance_customer_service',
    target_agent_version_id: 'published_v1',
    readiness_status: 'ready',
    blocking_reasons: [],
    governed_resolution_rate: 1,
    artifact_sufficiency_rate: 1,
    deterministic_gate_pass_rate: 1,
    suite_runs: [
      {
        source: 'core_regression',
        suite_id: 'active_agent_smoke',
        suite_version: '2026-06-21',
        analysis_id: 'analysis_active_agent_smoke',
        release_decision_status: 'passed',
        total_required_cases: 1,
        passed_required_cases: 1,
        governed_resolution_rate: 1,
        artifact_dir: '/tmp/analysis_active_agent_smoke',
      },
    ],
    capability_coverage: [
      {
        capability_path: 'evidence_answer',
        status: 'passed',
        required_cases: 1,
        passed_required_cases: 1,
        failed_required_cases: 0,
      },
    ],
    coding_agent_diagnostics: {
      diagnostics_version: 'coding-agent-diagnostics.v1',
      evaluated_case_count: 1,
      mean_quality_score: 0.82,
      diagnostic_blocker_candidate_count: 0,
      case_diagnostics: [],
    },
    artifact_dir: '/tmp/campaigns/active_agent_probe',
  }
}
