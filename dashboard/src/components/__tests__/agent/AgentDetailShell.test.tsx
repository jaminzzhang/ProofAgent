// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AgentDetailShell } from '../../agent/AgentDetailShell'

const renderWithRouter = (ui: React.ReactNode) =>
  render(<BrowserRouter>{ui}</BrowserRouter>)

describe('AgentDetailShell', () => {
  const mockModules = [
    { id: 'general', label: 'Overview' },
    { id: 'workflow', label: 'Workflow' },
    { id: 'knowledge', label: 'Knowledge' },
    { id: 'tools', label: 'Tools' },
    { id: 'policy', label: 'Policy' },
    { id: 'model', label: 'Model' },
    { id: 'memory', label: 'Memory' },
    { id: 'response', label: 'Response' },
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

  it('does not claim unsourced autosave status', () => {
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

    expect(screen.queryByText(/Auto-saved/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Last edited 2m ago/)).not.toBeInTheDocument()
  })

  it('renders Agent detail navigation with Overview and Design modules', () => {
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

    expect(screen.getByLabelText('Agent navigation')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Design' })).toBeInTheDocument()
    expect(screen.getByText('Workflow')).toBeInTheDocument()
    expect(screen.getByText('Knowledge')).toBeInTheDocument()
  })

  it('renders verify, release, and observe sections', () => {
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

    expect(screen.getByRole('heading', { name: 'Verify' })).toBeInTheDocument()
    expect(screen.getByText('Validate & Test')).toBeInTheDocument()
    expect(screen.getByText('Contract View')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Release' })).toBeInTheDocument()
    expect(screen.getByText('Versions')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Observe' })).toBeInTheDocument()
    expect(screen.getByText('Monitor')).toBeInTheDocument()
  })

  it('groups Agent navigation by design, verification, release, and observation work', () => {
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

    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Design' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Verify' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Release' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Observe' })).toBeInTheDocument()

    expect(screen.getByText('Workflow').closest('section')).toHaveTextContent('Design')
    expect(screen.getByText('Validate & Test').closest('section')).toHaveTextContent('Verify')
    expect(screen.getByText('Contract View').closest('section')).toHaveTextContent('Verify')
    expect(screen.getByText('Versions').closest('section')).toHaveTextContent('Release')
    expect(screen.getByText('Monitor').closest('section')).toHaveTextContent('Observe')
  })

  it('renders a full-window Agent Detail Page focus shell', () => {
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

    expect(screen.getByLabelText('Agent breadcrumb')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Agents' })).toHaveAttribute('href', '/agents')
    expect(screen.getByText('Test Agent')).toBeInTheDocument()
    expect(screen.getByTestId('agent-detail-layout')).toHaveClass('h-screen')
    expect(screen.getByTestId('agent-detail-layout')).toHaveClass('w-screen')
    expect(screen.queryByText('CONFIGURE')).not.toBeInTheDocument()
    expect(screen.queryByText('LIFECYCLE')).not.toBeInTheDocument()
  })

  it('does not render the old top grouped navigation descriptions', () => {
    renderWithRouter(
      <AgentDetailShell
        agentName="Test Agent"
        modules={mockModules}
        lifecycle={mockLifecycle}
        activeModule="model"
        onModuleChange={() => {}}
      >
        <div>Content</div>
      </AgentDetailShell>
    )

    expect(screen.queryByText('Define the agent contract and runtime dependencies.')).not.toBeInTheDocument()
    expect(screen.queryByText('Govern model behavior, tools, memory, and response disclosure.')).not.toBeInTheDocument()
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

    fireEvent.click(screen.getByRole('button', { name: 'Workflow' }))
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

    const workflowTab = screen.getByRole('button', { name: 'Workflow' })
    expect(workflowTab).toHaveAttribute('aria-current', 'page')
    expect(workflowTab).toHaveStyle({
      backgroundColor: 'var(--accent)',
      borderColor: 'var(--accent)',
      color: 'var(--accent-fg)',
    })
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
