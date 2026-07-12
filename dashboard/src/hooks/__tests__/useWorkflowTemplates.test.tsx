// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WorkflowTemplateDescriptor } from '../../api/types'

vi.mock('../../api/client', () => ({
  fetchWorkflowTemplates: vi.fn(),
}))

const TEMPLATES: WorkflowTemplateDescriptor[] = [
  {
    name: 'enterprise_qa',
    description: 'Legacy compatibility baseline.',
    descriptor_version: 'enterprise_qa.v1',
    stages: [],
  },
  {
    name: 'react_enterprise_qa_v3',
    description: 'Controlled ReAct Loop.',
    descriptor_version: 'react_enterprise_qa.v3',
    stages: [],
  },
]

describe('useWorkflowTemplates', () => {
  beforeEach(() => {
    // The hook caches the catalog at module scope; reset modules so each test
    // gets a fresh cache and a fresh client mock.
    vi.resetModules()
    vi.clearAllMocks()
  })

  it('loads the catalog on mount and exposes names plus descriptors', async () => {
    const { fetchWorkflowTemplates } = await import('../../api/client')
    vi.mocked(fetchWorkflowTemplates).mockResolvedValue({
      data: TEMPLATES,
      meta: { total: TEMPLATES.length },
    })
    const { useWorkflowTemplates } = await import('../useWorkflowTemplates')

    const { result } = renderHook(() => useWorkflowTemplates())

    await waitFor(() => expect(result.current.loaded).toBe(true))

    expect(result.current.error).toBeNull()
    expect(result.current.names).toEqual(['react_enterprise_qa_v3'])
    expect(result.current.templates).toHaveLength(1)
    expect(result.current.templates[0].name).toBe('react_enterprise_qa_v3')
  })

  it('reports an error and keeps an empty catalog when the fetch fails', async () => {
    const { fetchWorkflowTemplates } = await import('../../api/client')
    vi.mocked(fetchWorkflowTemplates).mockRejectedValue(new Error('boom'))
    const { useWorkflowTemplates } = await import('../useWorkflowTemplates')

    const { result } = renderHook(() => useWorkflowTemplates())

    await waitFor(() => expect(result.current.loaded).toBe(true))

    expect(result.current.error).toBe('boom')
    expect(result.current.names).toEqual([])
    expect(result.current.templates).toEqual([])
  })
})
