// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import {
  fetchEvaluationCampaign,
  fetchEvaluationCampaignCases,
  fetchEvaluationCampaigns,
} from '../../api/client'
import type { EvaluationCampaignSummary } from '../../api/types'
import { AppRoutes } from '../../router'

vi.mock('../../api/client', () => ({
  fetchEvaluationCampaigns: vi.fn(),
  fetchEvaluationCampaign: vi.fn(),
  fetchEvaluationCampaignCases: vi.fn(),
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

    render(
      <MemoryRouter initialEntries={['/evaluation-lab']}>
        <AppRoutes />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: 'Evaluation Lab' })).toBeInTheDocument()
    expect(await screen.findByText('active_agent_probe')).toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(screen.getByText('Intelligent Resolution')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('0 blocker candidates')).toBeInTheDocument()
    expect(screen.getByText('Evidence Answer')).toBeInTheDocument()
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(await screen.findByText('Case Drilldowns')).toBeInTheDocument()
    expect(screen.getByText('supported')).toBeInTheDocument()
    expect(screen.getByText('ANSWERED_WITH_CITATIONS')).toBeInTheDocument()
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
