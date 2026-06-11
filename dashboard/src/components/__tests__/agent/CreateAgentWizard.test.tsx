// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CreateAgentWizard } from '../../agent/CreateAgentWizard'

describe('CreateAgentWizard', () => {
  it('creates from the customer service example without exposing internal fixtures', async () => {
    const onCreate = vi.fn().mockResolvedValue({ agent_id: 'insurance_customer_service' })

    render(
      <CreateAgentWizard
        open
        onClose={() => {}}
        onCreated={() => {}}
        onCreate={onCreate}
      />,
    )

    expect(screen.getByRole('button', { name: /Insurance Customer Service/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Institution Insurance Specialist/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /ReAct Enterprise QA/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Enterprise QA/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Insurance Service QA/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Insurance Customer Service/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Create Agent' }))

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith(
        'examples/insurance_customer_service/agent.yaml',
        'Insurance Customer Service',
        'Provide read-only customer service for insurance policy and claim questions.',
      )
    })
  })

  it('creates from the institution insurance specialist example as a separate package', async () => {
    const onCreate = vi.fn().mockResolvedValue({ agent_id: 'institution_insurance_specialist' })

    render(
      <CreateAgentWizard
        open
        onClose={() => {}}
        onCreated={() => {}}
        onCreate={onCreate}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Institution Insurance Specialist/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Create Agent' }))

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith(
        'examples/institution_insurance_specialist/agent.yaml',
        'Institution Insurance Specialist',
        'Assist internal insurance institution specialists with governed business consultation and read-only business-system lookup.',
      )
    })
  })
})
