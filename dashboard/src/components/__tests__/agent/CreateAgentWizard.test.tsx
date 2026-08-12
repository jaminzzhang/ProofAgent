// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CreateAgentWizard } from '../../agent/CreateAgentWizard'

describe('CreateAgentWizard', () => {
  it('offers only the canonical V3 insurance specialist package', async () => {
    const onCreate = vi.fn().mockResolvedValue({
      agent_id: 'agent_management_insurance_specialist',
    })

    render(
      <CreateAgentWizard
        open
        onClose={() => {}}
        onCreated={() => {}}
        onCreate={onCreate}
        template={{
          id: 'agent_management_insurance_specialist',
          name: 'Agent Management Insurance Specialist',
          purpose: 'Assist internal insurance staff with governed, evidence-backed insurance knowledge consultation.',
          description: 'Operator-facing Controlled ReAct V3 consultation with production publication kept behind candidate gates.',
        }}
      />,
    )

    const cards = screen.getAllByRole('button', {
      name: /Agent Management Insurance Specialist/,
    })
    expect(cards).toHaveLength(1)
    expect(screen.queryByRole('button', { name: /Insurance Customer Service/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Institution Insurance Specialist/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/Customer-facing/)).not.toBeInTheDocument()
    expect(screen.getByText(/Controlled ReAct V3/)).toBeInTheDocument()

    fireEvent.click(cards[0])
    fireEvent.click(screen.getByRole('button', { name: 'Create Agent' }))

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith(
        'Agent Management Insurance Specialist',
        'Assist internal insurance staff with governed, evidence-backed insurance knowledge consultation.',
        expect.any(String),
      )
    })
    expect(screen.queryByText(/agent\.yaml/)).not.toBeInTheDocument()
  })
})
