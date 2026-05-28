// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AgentDetailShell } from '../../agent/AgentDetailShell'

const renderWithRouter = (ui: React.ReactNode) => render(<BrowserRouter>{ui}</BrowserRouter>)

describe('AgentDetailShell', () => {
  const mockModules = [
    { id: 'general', label: 'General' },
    { id: 'workflow', label: 'Workflow' },
    { id: 'knowledge', label: 'Knowledge' },
  ]

  const mockLifecycle = [
    { id: 'validate', label: 'Validate & Test' },
    { id: 'versions', label: 'Versions' },
    { id: 'contract', label: 'Contract View' },
    { id: 'monitor', label: 'Monitor' },
  ]

  it('renders agent name', () => {
    renderWithRouter(
      <AgentDetailShell
        agentName="Insurance Service Agent"
        modules={mockModules}
        lifecycle={mockLifecycle}
        activeModule="general"
        onModuleChange={() => {}}
      >
        <div>Content</div>
      </AgentDetailShell>
    )
    expect(screen.getByText('Insurance Service Agent')).toBeInTheDocument()
  })

  it('renders CONFIGURE section with modules', () => {
    renderWithRouter(
      <AgentDetailShell
        agentName="Test Agent"
        modules={mockModules}
        lifecycle={mockLifecycle}
        activeModule="general"
        onModuleChange={() => {}}
      >
        <div>Content</div>
      </AgentDetailShell>
    )

    expect(screen.getByText('CONFIGURE')).toBeInTheDocument()
    expect(screen.getByText('General')).toBeInTheDocument()
    expect(screen.getByText('Workflow')).toBeInTheDocument()
    expect(screen.getByText('Knowledge')).toBeInTheDocument()
  })

  it('renders LIFECYCLE section with tabs', () => {
    renderWithRouter(
      <AgentDetailShell
        agentName="Test Agent"
        modules={mockModules}
        lifecycle={mockLifecycle}
        activeModule="general"
        onModuleChange={() => {}}
      >
        <div>Content</div>
      </AgentDetailShell>
    )

    expect(screen.getByText('LIFECYCLE')).toBeInTheDocument()
    expect(screen.getByText('Validate & Test')).toBeInTheDocument()
    expect(screen.getByText('Versions')).toBeInTheDocument()
  })

  it('calls onModuleChange when tab is clicked', () => {
    const handleChange = vi.fn()
    renderWithRouter(
      <AgentDetailShell
        agentName="Test Agent"
        modules={mockModules}
        lifecycle={mockLifecycle}
        activeModule="general"
        onModuleChange={handleChange}
      >
        <div>Content</div>
      </AgentDetailShell>
    )

    fireEvent.click(screen.getByText('Workflow'))
    expect(handleChange).toHaveBeenCalledWith('workflow')
  })

  it('highlights active module', () => {
    renderWithRouter(
      <AgentDetailShell
        agentName="Test Agent"
        modules={mockModules}
        lifecycle={mockLifecycle}
        activeModule="workflow"
        onModuleChange={() => {}}
      >
        <div>Content</div>
      </AgentDetailShell>
    )

    const workflowTab = screen.getByText('Workflow').closest('button')
    expect(workflowTab).toHaveClass('bg-[var(--bg-hover)]')
  })

  it('renders children in content area', () => {
    renderWithRouter(
      <AgentDetailShell
        agentName="Test Agent"
        modules={mockModules}
        lifecycle={mockLifecycle}
        activeModule="general"
        onModuleChange={() => {}}
      >
        <div data-testid="content">Test Content</div>
      </AgentDetailShell>
    )

    expect(screen.getByTestId('content')).toBeInTheDocument()
    expect(screen.getByText('Test Content')).toBeInTheDocument()
  })
})
