// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { WorkflowStageLlmInteractionCapture } from '../../../api/types'
import { LlmInteractionReview } from '../LlmInteractionReview'

afterEach(() => {
  cleanup()
})

function interaction(
  overrides: Partial<WorkflowStageLlmInteractionCapture>,
): WorkflowStageLlmInteractionCapture {
  return {
    stage_id: 'reasoning',
    stage_label: 'Reasoning',
    role: 'planner',
    provider: 'deepseek',
    model: 'deepseek-v4-flash',
    request_json: {
      messages: [],
      model: 'deepseek-v4-flash',
      provider: 'deepseek',
      temperature: 0,
    },
    response_json: null,
    response_content_length: 0,
    response_json_parse_error_code: null,
    ...overrides,
  }
}

describe('LlmInteractionReview', () => {
  it('renders one card per request message with role and verbatim content', () => {
    render(
      <LlmInteractionReview
        interactions={[
          interaction({
            request_json: {
              messages: [
                { role: 'system', content: 'You are the Intent Resolver.' },
                { role: 'user', content: 'What products sell well?' },
              ],
            },
          }),
        ]}
      />,
    )

    expect(screen.getByText('system')).toBeInTheDocument()
    expect(screen.getByText('user')).toBeInTheDocument()
    expect(screen.getByText('You are the Intent Resolver.')).toBeInTheDocument()
    expect(screen.getByText('What products sell well?')).toBeInTheDocument()
  })

  it('shows each message character count and a copy affordance', () => {
    render(
      <LlmInteractionReview
        interactions={[
          interaction({
            request_json: {
              messages: [{ role: 'system', content: 'You are the Intent Resolver.' }],
            },
          }),
        ]}
      />,
    )

    // 'You are the Intent Resolver.' is 28 characters; the count lives on the
    // message card alongside a copy affordance for that card's content.
    const copyButton = screen.getByRole('button', { name: /copy system message/i })
    expect(copyButton).toBeInTheDocument()
    expect(copyButton.closest('div.rounded-md')).toHaveTextContent('28 chars')
  })

  it('renders the response as a formatted JSON block', () => {
    render(
      <LlmInteractionReview
        interactions={[
          interaction({
            response_json: { confidence: 'high', domain_intent: 'product_inquiry' },
          }),
        ]}
      />,
    )

    expect(screen.getByText(/Response/)).toBeInTheDocument()
    expect(screen.getByText(/"domain_intent": "product_inquiry"/)).toBeInTheDocument()
    expect(screen.getByText(/"confidence": "high"/)).toBeInTheDocument()
  })

  it('shows a human-readable diagnostic when the response failed to parse', () => {
    render(
      <LlmInteractionReview
        interactions={[
          interaction({
            response_json: null,
            response_json_parse_error_code: 'model_output_json_parse_failed',
            response_content_length: 120,
          }),
        ]}
      />,
    )

    expect(
      screen.getByText(/did not contain a valid JSON object/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/Response/)).toBeInTheDocument()
  })
})
