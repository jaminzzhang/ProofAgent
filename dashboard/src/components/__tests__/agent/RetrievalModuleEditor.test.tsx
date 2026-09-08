// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { RetrievalModuleEditor } from '../../agent/RetrievalModuleEditor'
import { updateAgentYamlField } from '../../../utils/agentYaml'

it('shows loader defaults, rejects blank/fractional/out-of-range budgets and saves corrected limits', () => {
  const saved = vi.fn()
  function Editor() {
    const [yaml, setYaml] = useState('retrieval:\n  strategy: single_step\n')
    return <RetrievalModuleEditor agentYaml={yaml} busy={false}
      onFieldChange={(path, value) => setYaml(current => updateAgentYamlField(current, path, value))}
      onSave={() => saved(yaml)} />
  }
  render(<Editor />)
  expect(screen.getByLabelText('Query timeout (seconds)')).toHaveValue(20)
  const input = screen.getByLabelText('Maximum required queries')
  for (const invalid of ['', '0', '6', '1.5']) {
    fireEvent.change(input, { target: { value: invalid } })
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  }
  fireEvent.change(input, { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(saved).toHaveBeenCalledWith(expect.stringContaining('max_queries: 5'))
  expect(saved).toHaveBeenCalledWith(expect.stringContaining('strategy: single_step'))
})
