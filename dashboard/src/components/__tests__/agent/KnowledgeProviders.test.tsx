// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import type { ExternalKnowledgeConfiguration } from '../../../api/types'
import { expect, it, vi } from 'vitest'
import { KnowledgeModuleEditor } from '../../agent/KnowledgeModuleEditor'

it('adds an Agentset namespace with provider-specific settings and clears incompatible data on switch', async () => {
  const save = vi.fn().mockResolvedValue('saved')
  function Editor() {
    const [config, setConfig] = useState<ExternalKnowledgeConfiguration>({revision: 4, bindings: []})
    return <KnowledgeModuleEditor config={config} mode="development" loading={false} error={null} busy={false}
      onSave={async bindings => { await save(bindings); setConfig({revision: 5, bindings}); return 'saved' }} />
  }
  render(<Editor />)
  fireEvent.click(screen.getByRole('button', { name: 'Add Agentset namespace' }))
  expect(screen.queryByLabelText('Dataset ID')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Namespace ID'), { target: { value: 'ns_manuals' } })
  fireEvent.change(screen.getByLabelText('Tenant ID (optional)'), { target: { value: 'Customer1' } })
  fireEvent.change(screen.getByLabelText('Secret Handle / environment variable name'), { target: { value: 'AGENTSET_KEY' } })
  fireEvent.change(screen.getByLabelText('Search method'), { target: { value: 'keyword' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save knowledge configuration' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith([expect.objectContaining({provider:'agentset', namespace_id:'ns_manuals', tenant_id:'Customer1', retrieval:expect.objectContaining({search_method:'keyword', rerank:true})})]))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save knowledge configuration' })).toBeDisabled())
  fireEvent.change(screen.getByLabelText('Knowledge provider'), { target: { value: 'dify' } })
  expect(screen.getByLabelText('Dataset ID')).toHaveValue('')
  expect(screen.getByLabelText('Secret Handle / environment variable name')).toHaveValue('')
  expect(screen.queryByLabelText('Tenant ID (optional)')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Search method')).toHaveValue('semantic_search')
})
