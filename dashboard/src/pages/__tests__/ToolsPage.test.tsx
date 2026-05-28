// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchConfigAgents } from '../../api/client'
import { ToolsPage } from '../ToolsPage'

vi.mock('../../api/client', () => ({
  fetchConfigAgents: vi.fn(),
  fetchConfigDraftContract: vi.fn(),
}))

describe('ToolsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows an error state when tool contracts cannot load', async () => {
    vi.mocked(fetchConfigAgents).mockRejectedValue(new Error('network down'))

    render(
      <MemoryRouter>
        <ToolsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Unable to load tool contracts.')).toBeInTheDocument()
  })
})
