// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EvidenceChunk } from '../../api/types'
import { EvidenceTab } from './EvidenceTab'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('EvidenceTab legacy identity fallback', () => {
  it('renders duplicate index-less legacy chunks without a React key warning', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const duplicate = {
      source: 'policy://travel#meals',
      citation: 'travel-policy.md#meals:L10-L18',
      status: 'accepted',
      admission_score: 0.84,
    } as unknown as EvidenceChunk

    render(<EvidenceTab chunks={[duplicate, { ...duplicate }]} />)

    expect(screen.getAllByText('travel-policy.md#meals:L10-L18')).toHaveLength(2)
    expect(
      consoleError.mock.calls.filter((call) =>
        call.some((argument) => String(argument).includes('unique "key"')),
      ),
    ).toHaveLength(0)
  })

  it('moves existing legacy card nodes when distinct chunks reorder', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const policy = {
      source: 'policy://travel#meals',
      citation: 'travel-policy.md#meals:L10-L18',
      status: 'accepted',
      fusion_rank: 1,
    } as unknown as EvidenceChunk
    const handbook = {
      source: 'policy://travel#lodging',
      citation: 'travel-policy.md#lodging:L20-L28',
      status: 'rejected',
      fusion_rank: 2,
    } as unknown as EvidenceChunk

    const { container, rerender } = render(<EvidenceTab chunks={[policy, handbook]} />)
    const list = container.firstElementChild as HTMLElement
    const [policyCard, handbookCard] = Array.from(list.children).slice(1)

    rerender(<EvidenceTab chunks={[handbook, policy]} />)

    const [firstCard, secondCard] = Array.from(list.children).slice(1)
    expect(firstCard).toBe(handbookCard)
    expect(secondCard).toBe(policyCard)
  })
})
