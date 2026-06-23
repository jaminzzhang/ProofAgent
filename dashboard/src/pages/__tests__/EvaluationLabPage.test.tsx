// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import {
  fetchEvaluationCampaign,
  fetchEvaluationCampaignCases,
  fetchEvaluationCampaigns,
  fetchEvaluationCampaignTrends,
  fetchEvaluationProductionSampleCandidates,
  fetchEvaluationProductionSamplePromotions,
  promoteEvaluationProductionSample,
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
  promoteEvaluationProductionSample: vi.fn(),
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
        {
          batch_id: 'prod_edge_cases',
          batch_dir: '/tmp/curation/prod_edge_cases',
          sample_id: 'prod_unreviewed',
          source_run_id: 'run_prod_unreviewed',
          curation_status: 'diagnostic_only',
          formal_scoring_allowed: false,
          run_purpose: 'production',
          safe_summary: {
            question_sha256: 'unreviewed-question-hash',
            question_text_length: 54,
            response_text_sha256: 'unreviewed-response-hash',
            response_text_length: 35,
          },
        },
      ],
      meta: { total: 2 },
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
    expect(screen.getByText('2 diagnostic candidates')).toBeInTheDocument()
    expect(screen.getByText('1 promoted samples')).toBeInTheDocument()
    expect(screen.getByText('Reviewer Queue')).toBeInTheDocument()
    expect(screen.getByText('1 needs review')).toBeInTheDocument()
    expect(screen.getByText('1 promoted')).toBeInTheDocument()
    expect(screen.getByText('prod_supported')).toBeInTheDocument()
    expect(screen.getByText('prod_unreviewed')).toBeInTheDocument()
    expect(screen.getAllByText('prod_edge_cases')).toHaveLength(2)
    expect(screen.getByText('Domain: domain-reviewer')).toBeInTheDocument()
    expect(screen.getByText('Harness: harness-reviewer')).toBeInTheDocument()
    expect(
      screen.getByText('Diagnostic only until domain and harness reviewers confirm.'),
    ).toBeInTheDocument()
  })

  it('promotes a production sample through explicit reviewer confirmation', async () => {
    const campaign = evaluationCampaign()
    vi.mocked(fetchEvaluationCampaigns).mockResolvedValue({
      data: [campaign],
      meta: { total: 1 },
    })
    vi.mocked(fetchEvaluationCampaign).mockResolvedValue(campaign)
    vi.mocked(fetchEvaluationCampaignCases).mockResolvedValue({
      campaign_id: 'active_agent_probe',
      data: [],
      meta: { total: 0 },
    })
    vi.mocked(fetchEvaluationCampaignTrends).mockResolvedValue({
      campaign_id: 'active_agent_probe',
      current_version: '2026-06-21',
      baseline_campaign_id: null,
      baseline_version: null,
      status: 'no_baseline',
      comparison_basis: {
        suite_versions: [],
      },
      metric_deltas: {},
    })
    vi.mocked(fetchEvaluationProductionSampleCandidates).mockResolvedValue({
      data: [
        {
          batch_id: 'prod_edge_cases',
          batch_dir: '/tmp/curation/prod_edge_cases',
          sample_id: 'prod_unreviewed',
          source_run_id: 'run_prod_unreviewed',
          curation_status: 'diagnostic_only',
          formal_scoring_allowed: false,
          run_purpose: 'production',
          safe_summary: {
            question_sha256: 'unreviewed-question-hash',
            question_text_length: 54,
            response_text_sha256: 'unreviewed-response-hash',
            response_text_length: 35,
          },
        },
      ],
      meta: { total: 1 },
    })
    vi.mocked(fetchEvaluationProductionSamplePromotions)
      .mockResolvedValueOnce({
        data: [],
        meta: { total: 0 },
      })
      .mockResolvedValueOnce({
        data: [
          {
            promotion_dir: '/tmp/curation/promoted/prod_unreviewed',
            promotion_record_path:
              '/tmp/curation/promoted/prod_unreviewed/production_sample_promotion.json',
            sample_id: 'prod_unreviewed',
            status: 'promoted',
            source_run_id: 'run_prod_unreviewed',
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
    vi.mocked(promoteEvaluationProductionSample).mockResolvedValue({
      promotion_dir: '/tmp/curation/promoted/prod_unreviewed',
      promotion_record_path:
        '/tmp/curation/promoted/prod_unreviewed/production_sample_promotion.json',
      sample_id: 'prod_unreviewed',
      status: 'promoted',
      suite_path: 'evaluation_suite.yaml',
      subject_manifest_path: 'evaluation_subjects.yaml',
    })

    render(
      <MemoryRouter initialEntries={['/evaluation-lab']}>
        <AppRoutes />
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Promote prod_unreviewed' }))

    fireEvent.change(screen.getByLabelText('Case ID'), {
      target: { value: 'prod_unreviewed_case' },
    })
    fireEvent.change(screen.getByLabelText('Question'), {
      target: { value: 'Redacted production policy support scenario.' },
    })
    fireEvent.change(screen.getByLabelText('Intent Type'), {
      target: { value: 'guidance' },
    })
    fireEvent.change(screen.getByLabelText('Expected Resolution'), {
      target: { value: 'answer_with_citations' },
    })
    fireEvent.change(screen.getByLabelText('Risk Class'), {
      target: { value: 'customer_service_fact' },
    })
    fireEvent.change(screen.getByLabelText('Capability Path'), {
      target: { value: 'evidence_answer' },
    })
    fireEvent.change(screen.getByLabelText('Expected Outcome'), {
      target: { value: 'ANSWERED_WITH_CITATIONS' },
    })
    fireEvent.change(screen.getByLabelText('Required Citation Refs'), {
      target: { value: 'policy,faq' },
    })
    fireEvent.change(screen.getByLabelText('Domain Reviewer'), {
      target: { value: 'domain-reviewer' },
    })
    fireEvent.click(screen.getByLabelText('Domain review confirmed'))
    fireEvent.change(screen.getByLabelText('Harness Reviewer'), {
      target: { value: 'harness-reviewer' },
    })
    fireEvent.click(screen.getByLabelText('Harness review confirmed'))
    fireEvent.click(screen.getByRole('button', { name: 'Promote Sample' }))

    await waitFor(() => {
      expect(promoteEvaluationProductionSample).toHaveBeenCalledWith({
        batch_id: 'prod_edge_cases',
        sample_id: 'prod_unreviewed',
        suite_id: 'production_edge_cases',
        suite_version: '2026-06-21',
        manifest_id: 'prod_unreviewed_subjects',
        case: {
          case_id: 'prod_unreviewed_case',
          question: 'Redacted production policy support scenario.',
          intent_type: 'guidance',
          expected_resolution: 'answer_with_citations',
          risk_class: 'customer_service_fact',
          capability_path: 'evidence_answer',
          expected_outcome: 'ANSWERED_WITH_CITATIONS',
          required_citation_refs: ['policy', 'faq'],
        },
        domain_review: {
          reviewer: 'domain-reviewer',
          confirmed: true,
        },
        harness_review: {
          reviewer: 'harness-reviewer',
          confirmed: true,
        },
      })
    })
    expect(await screen.findByText('Promotion record is available.')).toBeInTheDocument()
    expect(screen.getByText('Domain: domain-reviewer')).toBeInTheDocument()
    expect(screen.getByText('Harness: harness-reviewer')).toBeInTheDocument()
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
