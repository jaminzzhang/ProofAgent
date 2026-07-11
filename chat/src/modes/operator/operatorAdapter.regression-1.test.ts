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
          agent_id: 'enterprise_qa',
          run_id: 'run_2',
          outcome: 'ANSWERED_WITH_CITATIONS',
          final_output: 'Covered with citations.',
          evidence: rawEvidence,
          approval_state: null,
          links: { run_detail: '/runs/run_2', trace: '/trace/run_2', receipt: '/receipt/run_2' },
          conversation_id: 'conv_1',
          turn_id: 'turn_2',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

  const fetched = await fetchOperatorConversation('conv_1')
  const created = await createOperatorConversationRun('conv_1', 'What is covered?')

  expect(fetched.turns[0].evidence).toEqual(normalizedEvidence)
  expect(created.evidence).toEqual(normalizedEvidence)
})
