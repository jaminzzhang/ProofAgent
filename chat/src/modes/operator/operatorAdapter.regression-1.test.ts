import { afterEach, expect, test, vi } from 'vitest'

import {
  createOperatorConversationRun,
  fetchOperatorConversation,
} from './operatorAdapter'

afterEach(() => {
  vi.restoreAllMocks()
})

const rawEvidence = [
  {
    source: 'policy://travel#meals',
    citation: 'travel-policy.md#meals:L10-L18',
    status: 'accepted',
    scores: { relevance: 0.91 },
  },
  {
    source: '   ',
    citation: 'claims-guide.md#documents:L2-L8',
    status: 'accepted',
    scores: null,
  },
  {
    source: null,
    citation: null,
    status: 'rejected',
    scores: { relevance: 0.12 },
  },
]

const normalizedEvidence = [
  {
    source: 'policy://travel#meals',
    citation: 'travel-policy.md#meals:L10-L18',
    status: 'accepted',
    scores: { relevance: 0.91 },
  },
  {
    source: 'claims-guide.md#documents:L2-L8',
    citation: 'claims-guide.md#documents:L2-L8',
    status: 'accepted',
    scores: null,
  },
  {
    source: 'Source 3',
    citation: null,
    status: 'rejected',
    scores: { relevance: 0.12 },
  },
]

test('normalizes real API evidence identically for fetched turns and newly-created runs', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
  fetchMock
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          conversation_id: 'conv_1',
          agent_id: 'enterprise_qa',
          title: null,
          pinned: false,
          created_at: '2026-07-11T00:00:00Z',
          updated_at: '2026-07-11T00:01:00Z',
          turns: [
            {
              turn_id: 'turn_1',
              run_id: 'run_1',
              agent_id: 'enterprise_qa',
              question: 'What is covered?',
              final_output: 'Covered with citations.',
              outcome: 'ANSWERED_WITH_CITATIONS',
              created_at: '2026-07-11T00:01:00Z',
              context_admission: {
                admitted: false,
                turn_count: 0,
                included_turn_ids: [],
                summary: '',
                char_count: 0,
                max_turns: 3,
                dropped_turn_ids: [],
                fallback_reasons: [],
                clarification_turn_ids: [],
              },
              evidence: rawEvidence,
              approval_state: null,
              links: { run_detail: '/runs/run_1', trace: '/trace/run_1', receipt: '/receipt/run_1' },
            },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          conversation_id: 'conv_1',
          agent_id: 'enterprise_qa',
          turns: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    .mockResolvedValueOnce(new Response(JSON.stringify({
      contract_version: 'proofagent.run-execution.v1', run_id: 'run_2', state: 'queued',
      state_version: 1, question: 'What is covered?', agent_id: 'enterprise_qa',
      agent_version_id: 'version_1', result_available: false, artifact_manifest_id: null,
      failure_code: null, outcome: null, progress_url: '/api/runs/run_2/progress',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      contract_version: 'proofagent.run-execution.v1', run_id: 'run_2', state: 'succeeded',
      state_version: 4, question: 'What is covered?', agent_id: 'enterprise_qa',
      agent_version_id: 'version_1', result_available: true, artifact_manifest_id: 'manifest_1',
      failure_code: null, outcome: 'ANSWERED_WITH_CITATIONS',
      progress_url: '/api/runs/run_2/progress',
      final_output: { message: 'Covered with citations.' }, evidence_chunks: rawEvidence,
      approval_state: null,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      conversation_id: 'conv_1', agent_id: 'enterprise_qa', title: null, pinned: false,
      created_at: '2026-07-11T00:00:00Z', updated_at: '2026-07-11T00:02:00Z',
      turns: [{
        turn_id: 'turn_2', run_id: 'run_2', agent_id: 'enterprise_qa',
        question: 'What is covered?', final_output: 'Covered with citations.',
        outcome: 'ANSWERED_WITH_CITATIONS', created_at: '2026-07-11T00:02:00Z',
        context_admission: {
          admitted: false, turn_count: 0, included_turn_ids: [], summary: '', char_count: 0,
          max_turns: 3, dropped_turn_ids: [], fallback_reasons: [], clarification_turn_ids: [],
        },
        evidence: rawEvidence, approval_state: null,
        links: { run_detail: '/runs/run_2', trace: '/trace/run_2', receipt: '/receipt/run_2' },
      }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

  const fetched = await fetchOperatorConversation('conv_1')
  const created = await createOperatorConversationRun('conv_1', 'What is covered?')

  expect(fetched.turns[0].evidence).toEqual(normalizedEvidence)
  expect(created.evidence).toEqual(normalizedEvidence)
})
