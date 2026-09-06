// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { KnowledgePage } from '../KnowledgePage'
import { LocaleProvider } from '../../i18n/locale'
import { fetchKnowledgeServiceWorkspace } from '../../api/knowledgeService'
vi.mock('../../api/knowledgeService', () => ({ fetchKnowledgeServiceWorkspace: vi.fn() }))

it('routes external knowledge configuration to Agents without contacting KSS', () => {
  render(<MemoryRouter><LocaleProvider><KnowledgePage /></LocaleProvider></MemoryRouter>)
  expect(screen.getByRole('heading', { name: 'External knowledge bases' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Configure in Agents' })).toHaveAttribute('href', '/agents')
  expect(screen.getByRole('link', { name: 'Dify Knowledge API guide' })).toHaveAttribute('href', 'https://docs.dify.ai/en/api-reference/guides/knowledge')
  expect(fetchKnowledgeServiceWorkspace).not.toHaveBeenCalled()
  expect(screen.queryByText(/KSS/)).not.toBeInTheDocument()
})
