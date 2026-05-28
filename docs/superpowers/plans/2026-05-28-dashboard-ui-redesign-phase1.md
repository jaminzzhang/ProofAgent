# Dashboard UI Redesign - Phase 1: Navigation Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the sidebar into MONITORING and CONFIGURATION sections, and create the agent detail view shell with vertical tabs for CONFIGURE and LIFECYCLE.

**Architecture:** The sidebar uses two grouped sections with visible headers. Agent detail view uses vertical tabs in the main content area, split into CONFIGURE (8 modules) and LIFECYCLE (4 tabs). This foundation supports incremental addition of configuration editors and lifecycle features.

**Tech Stack:** React, React Router, TypeScript, Tailwind CSS

---

## File Structure

```
dashboard/src/
├── components/
│   ├── Sidebar.tsx (modify: add section headers and grouping)
│   ├── navigation/
│   │   ├── NavigationSection.tsx (create: reusable section header component)
│   │   └── NavigationItem.tsx (create: navigation item with icon and label)
│   └── agent/
│       └── AgentDetailShell.tsx (create: vertical tab layout wrapper)
├── pages/
│   ├── AgentsPage.tsx (modify: update to show agent list with detail navigation)
│   └── AgentDetailPage.tsx (modify: integrate new shell structure)

dashboard/src/components/__tests__/
├── navigation/
│   ├── NavigationSection.test.tsx (create)
│   └── NavigationItem.test.tsx (create)
└── agent/
    └── AgentDetailShell.test.tsx (create)
```

---

## Task 1: Navigation Section Component

**Files:**
- Create: `dashboard/src/components/navigation/NavigationSection.tsx`
- Create: `dashboard/src/components/__tests__/navigation/NavigationSection.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/components/__tests__/navigation/NavigationSection.test.tsx
import { render, screen } from '@testing-library/react'
import { NavigationSection } from '../../navigation/NavigationSection'

describe('NavigationSection', () => {
  it('renders section title', () => {
    render(<NavigationSection title="MONITORING" />)
    expect(screen.getByText('MONITORING')).toBeInTheDocument()
  })

  it('renders children', () => {
    render(
      <NavigationSection title="MONITORING">
        <div data-testid="child">Child content</div>
      </NavigationSection>
    )
    expect(screen.getByTestId('child')).toBeInTheDocument()
  })

  it('applies uppercase styling to title', () => {
    render(<NavigationSection title="MONITORING" />)
    const title = screen.getByText('MONITORING')
    expect(title).toHaveClass('uppercase')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- NavigationSection.test.tsx --watchAll=false`
Expected: FAIL with "Cannot find module '../../navigation/NavigationSection'"

- [ ] **Step 3: Write minimal implementation**

```typescript
// dashboard/src/components/navigation/NavigationSection.tsx
interface NavigationSectionProps {
  title: string
  children?: React.ReactNode
}

export function NavigationSection({ title, children }: NavigationSectionProps) {
  return (
    <div className="mb-6">
      <h3 className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h3>
      <div className="space-y-1">
        {children}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- NavigationSection.test.tsx --watchAll=false`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/navigation/NavigationSection.tsx
git add dashboard/src/components/__tests__/navigation/NavigationSection.test.tsx
git commit -m "feat: add NavigationSection component for sidebar grouping"
```

---

## Task 2: Navigation Item Component

**Files:**
- Create: `dashboard/src/components/navigation/NavigationItem.tsx`
- Create: `dashboard/src/components/__tests__/navigation/NavigationItem.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/components/__tests__/navigation/NavigationItem.test.tsx
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { NavigationItem } from '../../navigation/NavigationItem'

const renderWithRouter = (component: React.ReactNode) => {
  return render(<BrowserRouter>{component}</BrowserRouter>)
}

describe('NavigationItem', () => {
  it('renders label and icon', () => {
    const icon = <svg data-testid="icon" />
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={icon} />)
    
    expect(screen.getByText('Test Item')).toBeInTheDocument()
    expect(screen.getByTestId('icon')).toBeInTheDocument()
  })

  it('applies active styles when route matches', () => {
    window.history.pushState({}, '', '/test')
    const icon = <svg />
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={icon} />)
    
    const link = screen.getByText('Test Item').closest('a')
    expect(link).toHaveClass('bg-[var(--bg-hover)]')
  })

  it('applies inactive styles when route does not match', () => {
    window.history.pushState({}, '', '/other')
    const icon = <svg />
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={icon} />)
    
    const link = screen.getByText('Test Item').closest('a')
    expect(link).toHaveClass('text-[var(--text-secondary)]')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- NavigationItem.test.tsx --watchAll=false`
Expected: FAIL with "Cannot find module '../../navigation/NavigationItem'"

- [ ] **Step 3: Write minimal implementation**

```typescript
// dashboard/src/components/navigation/NavigationItem.tsx
import { NavLink, useLocation } from 'react-router-dom'

interface NavigationItemProps {
  to: string
  label: string
  icon: React.ReactNode
}

export function NavigationItem({ to, label, icon }: NavigationItemProps) {
  const location = useLocation()
  const isHash = to.startsWith('#')
  const isActive = isHash 
    ? location.hash === to 
    : (to === '/' ? location.pathname === '/' : location.pathname.startsWith(to)) && location.hash === ''

  return (
    <NavLink
      to={to}
      className={`group flex items-center gap-3 px-3 py-2 text-[14px] font-medium transition-colors rounded-md ${
        isActive
          ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
          : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
      }`}
    >
      <span className={`transition-colors ${isActive ? 'text-current' : 'text-[var(--text-muted)] group-hover:text-current'}`}>
        {icon}
      </span>
      {label}
    </NavLink>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- NavigationItem.test.tsx --watchAll=false`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/navigation/NavigationItem.tsx
git add dashboard/src/components/__tests__/navigation/NavigationItem.test.tsx
git commit -m "feat: add NavigationItem component with active state styling"
```

---

## Task 3: Restructure Sidebar with Sections

**Files:**
- Modify: `dashboard/src/components/Sidebar.tsx`

- [ ] **Step 1: Update Sidebar to use NavigationSection and NavigationItem**

Replace the entire `Sidebar.tsx` content:

```typescript
// dashboard/src/components/Sidebar.tsx
import { NavigationSection } from './navigation/NavigationSection'
import { NavigationItem } from './navigation/NavigationItem'

const MONITORING_ITEMS = [
  { 
    to: '/', 
    label: 'Overview',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18"/><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"/></svg>
  },
  { 
    to: '/runs', 
    label: 'Runs',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
  },
  {
    to: '/handoffs',
    label: 'Handoffs',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 8h10"/><path d="M7 12h6"/><path d="M5 20l-1.5-3A8 8 0 1 1 12 20z"/></svg>
  },
  { 
    to: '#approvals', 
    label: 'Approvals',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
  },
]

const CONFIGURATION_ITEMS = [
  {
    to: '/agents',
    label: 'Agents',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l7 4v10l-7 4-7-4V7z"/><path d="M12 12l7-4"/><path d="M12 12v8"/><path d="M12 12L5 8"/></svg>
  },
  { 
    to: '#policies', 
    label: 'Policies',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
  },
  {
    to: '#knowledge',
    label: 'Knowledge',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
  },
  {
    to: '#tools',
    label: 'Tools',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
  },
]

export function Sidebar() {
  return (
    <aside className="w-56 shrink-0 border-r border-[var(--border)] bg-[var(--bg-surface)] flex flex-col overflow-y-auto pt-6 pb-4 max-md:w-full max-md:border-r-0 max-md:border-b max-md:pt-2 max-md:pb-2">
      <nav className="flex-1 px-3 max-md:flex max-md:gap-1 max-md:space-y-0 max-md:overflow-x-auto" aria-label="Main navigation">
        <NavigationSection title="Monitoring">
          {MONITORING_ITEMS.map((item) => (
            <NavigationItem
              key={item.label}
              to={item.to}
              label={item.label}
              icon={item.icon}
            />
          ))}
        </NavigationSection>

        <NavigationSection title="Configuration">
          {CONFIGURATION_ITEMS.map((item) => (
            <NavigationItem
              key={item.label}
              to={item.to}
              label={item.label}
              icon={item.icon}
            />
          ))}
        </NavigationSection>
      </nav>

      {/* Settings at the bottom */}
      <div className="px-3 mt-auto max-md:hidden">
        <NavigationItem
          to="#settings"
          label="Settings"
          icon={<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>}
        />
      </div>
    </aside>
  )
}
```

- [ ] **Step 2: Verify sidebar renders correctly**

Run: `cd dashboard && npm run dev`

Open browser to http://localhost:5173 and verify:
- Sidebar shows "MONITORING" section header
- Overview, Runs, Handoffs, Approvals appear under MONITORING
- Sidebar shows "CONFIGURATION" section header
- Agents, Policies, Knowledge, Tools appear under CONFIGURATION
- Settings appears at bottom

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/Sidebar.tsx
git commit -m "feat: restructure sidebar with MONITORING and CONFIGURATION sections"
```

---

## Task 4: Agent Detail Shell Component

**Files:**
- Create: `dashboard/src/components/agent/AgentDetailShell.tsx`
- Create: `dashboard/src/components/__tests__/agent/AgentDetailShell.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/src/components/__tests__/agent/AgentDetailShell.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { AgentDetailShell } from '../../agent/AgentDetailShell'

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
    render(
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
    render(
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
    render(
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
    const handleChange = jest.fn()
    render(
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
    render(
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
    render(
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- AgentDetailShell.test.tsx --watchAll=false`
Expected: FAIL with "Cannot find module '../../agent/AgentDetailShell'"

- [ ] **Step 3: Write minimal implementation**

```typescript
// dashboard/src/components/agent/AgentDetailShell.tsx
import { Link } from 'react-router-dom'

interface Tab {
  id: string
  label: string
}

interface AgentDetailShellProps {
  agentName: string
  modules: Tab[]
  lifecycle: Tab[]
  activeModule: string
  onModuleChange: (moduleId: string) => void
  children: React.ReactNode
}

export function AgentDetailShell({
  agentName,
  modules,
  lifecycle,
  activeModule,
  onModuleChange,
  children,
}: AgentDetailShellProps) {
  return (
    <div className="w-full min-w-0 max-w-6xl space-y-6 overflow-hidden">
      {/* Header */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <Link to="/agents" className="text-xs font-medium tracking-wide text-[var(--text-muted)] hover:text-[var(--text-primary)] uppercase">
          &larr; Back to Agents
        </Link>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)] mt-4">
          {agentName}
        </h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Auto-saved draft • Last edited 2m ago
        </p>
      </div>

      {/* Vertical tabs + content */}
      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        {/* Tab navigation */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
          {/* CONFIGURE section */}
          <div className="p-4 border-b border-[var(--border)]">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
              CONFIGURE
            </h3>
            <div className="space-y-1">
              {modules.map((module) => (
                <button
                  key={module.id}
                  onClick={() => onModuleChange(module.id)}
                  className={`w-full text-left px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                    activeModule === module.id
                      ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                      : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                  }`}
                >
                  {module.label}
                </button>
              ))}
            </div>
          </div>

          {/* LIFECYCLE section */}
          <div className="p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
              LIFECYCLE
            </h3>
            <div className="space-y-1">
              {lifecycle.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => onModuleChange(tab.id)}
                  className={`w-full text-left px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                    activeModule === tab.id
                      ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                      : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Content area */}
        <div className="min-w-0">
          {children}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- AgentDetailShell.test.tsx --watchAll=false`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/agent/AgentDetailShell.tsx
git add dashboard/src/components/__tests__/agent/AgentDetailShell.test.tsx
git commit -m "feat: add AgentDetailShell with CONFIGURE and LIFECYCLE sections"
```

---

## Task 5: Integrate Agent Detail Shell into AgentDetailPage

**Files:**
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`
- Modify: `dashboard/src/pages/AgentsPage.tsx`

**Important: Feature Regression Acknowledgement**

This task intentionally removes the existing Workflow node editor and Validation workspace UI. These features will be re-implemented in Phase 3 (Validation) and Phase 4 (Workflow) with improved UX. The underlying API calls (`saveWorkflow()`, `runValidation()`) and state (`selectedNodeId`, `validationQuestion`) will remain in the component but unused until Phase 3-4. This is acceptable because:
- Phase 1 focuses on navigation foundation
- Preserving old UI inside new shell creates inconsistent UX
- Re-implementation allows better integration with new design patterns

- [ ] **Step 1: Update AgentDetailPage to use AgentDetailShell**

Replace the return statement in `AgentDetailPage.tsx` (keep all the state and handlers, just update the JSX):

```typescript
// Find the return statement around line 128 and replace it with:

const CONFIGURE_MODULES = [
  { id: 'general', label: 'General' },
  { id: 'workflow', label: 'Workflow' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'tools', label: 'Tools' },
  { id: 'policy', label: 'Policy' },
  { id: 'model', label: 'Model' },
  { id: 'memory', label: 'Memory' },
  { id: 'response', label: 'Response' },
]

const LIFECYCLE_TABS = [
  { id: 'validate', label: 'Validate & Test' },
  { id: 'versions', label: 'Versions' },
  { id: 'contract', label: 'Contract View' },
  { id: 'monitor', label: 'Monitor' },
]

return (
  <AgentDetailShell
    agentName={displayName}
    modules={CONFIGURE_MODULES}
    lifecycle={LIFECYCLE_TABS}
    activeModule={activeTab}
    onModuleChange={(moduleId) => setActiveTab(moduleId as Tab)}
  >
    {/* General module - basic agent info */}
    {activeTab === 'general' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <div className="flex items-center justify-between border-b border-[var(--border)] pb-4 mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            General Configuration
          </h3>
          <button
            onClick={saveBasics}
            disabled={busy === 'basics'}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {busy === 'basics' ? 'Saving...' : 'Save'}
          </button>
        </div>
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
              Display Name
            </label>
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
              Purpose
            </label>
            <textarea
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
              rows={3}
              className="w-full resize-none bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div className="flex gap-2 text-xs font-mono text-[var(--text-muted)]">
            <span>{draft.agent_id}</span>
            <span>•</span>
            <span>{draft.draft_id}</span>
            <span>•</span>
            <span>{draft.validation_records.length} validations</span>
            <span>•</span>
            <span>{versions.length} versions</span>
          </div>
        </div>
      </div>
    )}

    {/* Workflow module - placeholder */}
    {activeTab === 'workflow' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Workflow Configuration
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Workflow nodes and configuration will be implemented in Phase 4.
        </p>
      </div>
    )}

    {/* Knowledge module - placeholder */}
    {activeTab === 'knowledge' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Knowledge Configuration
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Knowledge providers and bindings will be implemented in Phase 2.
        </p>
      </div>
    )}

    {/* Tools module - placeholder */}
    {activeTab === 'tools' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Tools Configuration
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Tool contracts and bindings will be implemented in Phase 2.
        </p>
      </div>
    )}

    {/* Policy module - placeholder */}
    {activeTab === 'policy' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Policy Configuration
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Policy rules will be implemented in Phase 2.
        </p>
      </div>
    )}

    {/* Model module - placeholder */}
    {activeTab === 'model' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Model Configuration
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Model providers and roles will be implemented in Phase 2.
        </p>
      </div>
    )}

    {/* Memory module - placeholder */}
    {activeTab === 'memory' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Memory Configuration
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Memory providers and scopes will be implemented in Phase 2.
        </p>
      </div>
    )}

    {/* Response module - placeholder */}
    {activeTab === 'response' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Response Configuration
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Response disclosure and language settings will be implemented in Phase 2.
        </p>
      </div>
    )}

    {/* Validate & Test lifecycle tab - placeholder */}
    {activeTab === 'validate' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Validate & Test
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Validation workspace will be implemented in Phase 3.
        </p>
      </div>
    )}

    {/* Versions lifecycle tab - existing code */}
    {activeTab === 'versions' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <div className="flex items-center justify-between border-b border-[var(--border)] pb-4">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              Published Versions
            </h3>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              {activeVersionId ?? 'No active version'}
            </p>
          </div>
          <button
            onClick={publishDraft}
            disabled={busy === 'publish' || !latestValidation}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            Publish
          </button>
        </div>
        {versionsLoading ? (
          <div className="py-8 flex justify-center"><LoadingSpinner size="sm" /></div>
        ) : versions.length === 0 ? (
          <EmptyState message="No published versions." />
        ) : (
          <div className="mt-4 divide-y divide-[var(--border)]">
            {versions.map((version) => (
              <div key={version.version_id} className="flex items-center justify-between gap-4 py-3">
                <div>
                  <div className="font-mono text-xs text-[var(--text-primary)]">{version.version_id}</div>
                  <div className="mt-1 text-xs text-[var(--text-muted)]">validated by {version.validation_run_id}</div>
                </div>
                {version.version_id === activeVersionId ? (
                  <span className="rounded-full bg-[var(--bg-hover)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)]">
                    Active
                  </span>
                ) : (
                  <button
                    onClick={() => rollback(version.version_id)}
                    disabled={busy === `rollback-${version.version_id}`}
                    className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                  >
                    Rollback
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    )}

    {/* Contract View lifecycle tab - existing code */}
    {activeTab === 'contract' && (
      <div className="grid gap-5">
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">agent.yaml</h3>
          <CodeBlock>{agentYaml}</CodeBlock>
        </section>
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">policy.yaml</h3>
          <CodeBlock>{contract.policy_yaml}</CodeBlock>
        </section>
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">tools.yaml</h3>
          <CodeBlock>{contract.tools_yaml}</CodeBlock>
        </section>
      </div>
    )}

    {/* Monitor lifecycle tab - placeholder */}
    {activeTab === 'monitor' && (
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
          Agent Monitoring
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Recent runs, success rate, and validation history will be implemented in Phase 3.
        </p>
      </div>
    )}

    {/* Status and error messages */}
    {(status || actionError) && (
      <div className={`fixed bottom-4 right-4 rounded-md border px-4 py-3 text-sm shadow-lg ${
        actionError
          ? 'border-[var(--danger)]/40 bg-[var(--danger)]/10 text-[var(--danger)]'
          : 'border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)]'
      }`}>
        {actionError ?? status}
      </div>
    )}
  </AgentDetailShell>
)
```

- [ ] **Step 2: Update AgentDetailPage to use AgentDetailShell**

Add the import at the top of the file:
```typescript
import { AgentDetailShell } from '../components/agent/AgentDetailShell'
```

Update the Tab type definition (around line 17):
```typescript
type Tab = 'general' | 'workflow' | 'knowledge' | 'tools' | 'policy' | 'model' | 'memory' | 'response' | 'validate' | 'versions' | 'contract' | 'monitor'
```

Update the initial state (around line 28):
```typescript
const [activeTab, setActiveTab] = useState<Tab>('general')
```

Remove the old "Back to Agents" link from the header (around lines 131-133) since it's now in AgentDetailShell.

Remove the old tab navigation code (the section with the horizontal tabs around lines 178-199).

- [ ] **Step 3: Verify agent detail page renders correctly**

Run: `cd dashboard && npm run dev`

Navigate to an agent detail page and verify:
- Agent name appears in header
- "Auto-saved draft" message appears
- CONFIGURE section shows 8 modules (General, Workflow, Knowledge, Tools, Policy, Model, Memory, Response)
- LIFECYCLE section shows 4 tabs (Validate & Test, Versions, Contract View, Monitor)
- Clicking different tabs switches the content area
- General tab shows the form fields with Save button
- Versions and Contract View tabs show existing functionality
- Other tabs show placeholder messages

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/AgentDetailPage.tsx
git commit -m "feat: integrate AgentDetailShell into AgentDetailPage"
```

---

## Task 6: Add Create Agent Button to AgentsPage

**Files:**
- Modify: `dashboard/src/pages/AgentsPage.tsx`

- [ ] **Step 1: Add "Create Agent" button**

Add this button next to the Import button (around line 34):

```typescript
<button
  onClick={() => {/* TODO: Implement agent creation wizard in Phase 4 */}}
  className="shrink-0 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90"
>
  + Create Agent
</button>
```

- [ ] **Step 2: Verify AgentsPage renders correctly**

Run: `cd dashboard && npm run dev`

Navigate to /agents and verify:
- "+ Create Agent" button appears next to Import button
- Clicking an agent in the table navigates to the agent detail page
- Agent detail page shows the new shell with vertical tabs

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/AgentsPage.tsx
git commit -m "feat: add Create Agent button to AgentsPage"
```

---

## Task 7: End-to-End Verification

**Files:**
- No new files

- [ ] **Step 1: Run all tests**

Run: `cd dashboard && npm test -- --watchAll=false`

Expected: All tests pass (NavigationSection, NavigationItem, AgentDetailShell tests)

- [ ] **Step 2: Run TypeScript type checking**

Run: `cd dashboard && npx tsc --noEmit`

Expected: No type errors

- [ ] **Step 3: Run full development server**

Run: `cd dashboard && npm run dev`

Navigate through the application and verify:
- Sidebar shows MONITORING and CONFIGURATION sections
- All navigation items work correctly
- Agents list page shows "+ Create Agent" button
- Clicking an agent opens the detail page
- Agent detail page shows vertical tabs with CONFIGURE and LIFECYCLE sections
- All tabs are clickable and show appropriate content
- Versions and Contract View tabs show existing functionality
- Other tabs show placeholder messages

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: complete Phase 1 navigation foundation"
```

---

## Summary

Phase 1 delivers:
- ✅ Sidebar restructured with MONITORING and CONFIGURATION sections
- ✅ Agent detail view with vertical tabs (8 CONFIGURE modules + 4 LIFECYCLE tabs)
- ✅ General module with basic agent info editing
- ✅ Versions and Contract View tabs preserve existing functionality
- ✅ Placeholder content for modules to be implemented in Phase 2-5
- ✅ Full test coverage for new components

**Next:** Phase 2 will implement the 8 configuration modules with hybrid forms + YAML editor.
