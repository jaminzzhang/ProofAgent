# Dashboard UI Redesign - Phase 2: Configuration Modules

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the 7 placeholder tabs (Workflow, Knowledge, Tools, Policy, Model, Memory, Response) with working form editors that read and write Agent Contract YAML fields through the existing `agentYaml.ts` utility.

**Architecture:** Each module defines its fields as a static config array (label, YAML path, input type). A shared `ModuleEditor` component renders forms from the config and provides a YAML toggle. The AgentDetailPage passes `agentYaml` string and `updateAgentYamlField` to each module.

**Tech Stack:** React, TypeScript, Tailwind CSS, existing `dashboard/src/utils/agentYaml.ts`

---

## File Structure

```
dashboard/src/
├── components/
│   └── agent/
│       ├── ModuleEditor.tsx (create: reusable form + YAML toggle wrapper)
│       └── module-configs/
│           ├── workflow.ts (create: Workflow field definitions)
│           ├── knowledge.ts (create: Knowledge + Retrieval field definitions)
│           ├── tools.ts (create: Tools field definitions)
│           ├── policy.ts (create: Policy field definitions)
│           ├── model.ts (create: Model + Planner + Review field definitions)
│           ├── memory.ts (create: Memory field definitions)
│           └── response.ts (create: Response field definitions)
├── pages/
│   └── AgentDetailPage.tsx (modify: replace placeholder tabs with ModuleEditor)
```

---

## Agent YAML Structure (reference)

```yaml
name: insurance_customer_service
purpose: "..."
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    provider: sqlite
    uri: memory
knowledge:
  provider: local_markdown
  params:
    path: ./knowledge
retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2
react:
  max_steps: 5
  max_tool_calls: 1
  record_reasoning_summary: true
  planner:
    provider: deterministic
    name: insurance-customer-planner-demo
review:
  mode: auto
  subagent:
    provider: deterministic
    name: insurance-customer-review-demo
    timeout_seconds: 5
    max_output_tokens: 500
    fail_closed: true
response:
  include_reasoning_summary: false
  include_review_results: false
model:
  provider: deterministic
  name: insurance-customer-demo
policy:
  file: ./policy.yaml
tools:
  file: ./tools.yaml
memory:
  provider: local
  scopes:
    case:
      enabled: true
      retention_days: 30
      max_records: 5
      allow_restricted: false
    user:
      enabled: false
    shared:
      enabled: false
```

---

## Task 1: ModuleEditor Component

**Files:**
- Create: `dashboard/src/components/agent/ModuleEditor.tsx`

- [ ] **Step 1: Create ModuleEditor**

```typescript
// dashboard/src/components/agent/ModuleEditor.tsx
import { useState } from 'react'
import { CodeBlock } from '../CodeBlock'

interface FieldConfig {
  label: string
  path: string[]
  input: 'text' | 'number' | 'select'
  options?: string[]
  description?: string
}

interface ModuleEditorProps {
  title: string
  description?: string
  fields: FieldConfig[]
  yamlSection: string
  agentYaml: string
  onFieldChange: (path: string[], value: string) => void
  onSave: () => void
  busy: boolean
}

export function ModuleEditor({
  title,
  description,
  fields,
  yamlSection,
  agentYaml,
  onFieldChange,
  onSave,
  busy,
}: ModuleEditorProps) {
  const [showYaml, setShowYaml] = useState(false)

  const sectionYaml = extractSectionYaml(agentYaml, yamlSection)

  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
      <div className="flex items-center justify-between border-b border-[var(--border)] p-5">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {title}
          </h3>
          {description && (
            <p className="mt-1 text-sm text-[var(--text-muted)]">{description}</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowYaml(!showYaml)}
            className={`text-xs font-medium px-3 py-1.5 rounded-md transition-colors ${
              showYaml
                ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
            }`}
          >
            {showYaml ? 'Hide YAML' : 'Show YAML'}
          </button>
          <button
            onClick={onSave}
            disabled={busy}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {busy ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {showYaml && sectionYaml && (
        <div className="border-b border-[var(--border)] p-5">
          <CodeBlock>{sectionYaml}</CodeBlock>
        </div>
      )}

      <div className="p-5">
        <div className="grid gap-4 md:grid-cols-2">
          {fields.map((field) => (
            <label key={field.path.join('.')} className="block">
              <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                {field.label}
              </span>
              {field.description && (
                <span className="block text-xs text-[var(--text-muted)] mb-2">{field.description}</span>
              )}
              {field.input === 'select' && field.options ? (
                <select
                  value={readFieldValue(agentYaml, field.path)}
                  onChange={(e) => onFieldChange(field.path, e.target.value)}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                >
                  {field.options.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.input}
                  value={readFieldValue(agentYaml, field.path)}
                  onChange={(e) => onFieldChange(field.path, e.target.value)}
                  className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                />
              )}
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}

function readFieldValue(agentYaml: string, path: string[]): string {
  const lines = agentYaml.split('\n')
  
  if (path.length === 1) {
    for (const line of lines) {
      const match = line.match(new RegExp(`^${path[0]}:\\s*(.*)$`))
      if (match) return parseYamlValue(match[1])
    }
    return ''
  }

  const sectionStart = findSectionStart(lines, path[0])
  if (sectionStart === -1) return ''

  if (path.length === 2) {
    for (let i = sectionStart + 1; i < lines.length; i++) {
      if (lines[i].trim() && !lines[i].startsWith(' ')) break
      const match = lines[i].match(new RegExp(`^  ${path[1]}:\\s*(.*)$`))
      if (match) return parseYamlValue(match[1])
    }
    return ''
  }

  if (path.length === 3) {
    let parentStart = -1
    let parentEnd = lines.length
    for (let i = sectionStart + 1; i < lines.length; i++) {
      if (lines[i].trim() && !lines[i].startsWith(' ')) break
      if (lines[i].match(new RegExp(`^  ${path[1]}:`))) {
        parentStart = i
      } else if (parentStart !== -1 && lines[i].trim() && !lines[i].startsWith('    ')) {
        parentEnd = i
        break
      }
    }
    if (parentStart === -1) return ''
    for (let i = parentStart + 1; i < parentEnd; i++) {
      const match = lines[i].match(new RegExp(`^    ${path[2]}:\\s*(.*)$`))
      if (match) return parseYamlValue(match[1])
    }
    return ''
  }

  return ''
}

function extractSectionYaml(agentYaml: string, sectionName: string): string {
  const lines = agentYaml.split('\n')
  const start = findSectionStart(lines, sectionName)
  if (start === -1) return ''
  
  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].trim() && !lines[i].startsWith(' ')) {
      end = i
      break
    }
  }
  return lines.slice(start, end).join('\n')
}

function findSectionStart(lines: string[], sectionName: string): number {
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].match(new RegExp(`^${sectionName}:`))) return i
  }
  return -1
}

function parseYamlValue(value: string): string {
  const trimmed = value.trim()
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1)
  }
  return trimmed
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/components/agent/ModuleEditor.tsx
git commit -m "feat: add ModuleEditor component with form + YAML toggle"
```

---

## Task 2: Module Config Files

**Files:**
- Create: `dashboard/src/components/agent/module-configs/workflow.ts`
- Create: `dashboard/src/components/agent/module-configs/knowledge.ts`
- Create: `dashboard/src/components/agent/module-configs/tools.ts`
- Create: `dashboard/src/components/agent/module-configs/policy.ts`
- Create: `dashboard/src/components/agent/module-configs/model.ts`
- Create: `dashboard/src/components/agent/module-configs/memory.ts`
- Create: `dashboard/src/components/agent/module-configs/response.ts`

Each file exports a `FieldConfig[]` array. Use the import from ModuleEditor or define the interface inline.

- [ ] **Step 1: Create all 7 config files**

`module-configs/workflow.ts`:
```typescript
export const WORKFLOW_FIELDS = [
  { label: 'Runtime', path: ['workflow', 'runtime'], input: 'select' as const, options: ['langgraph'] },
  { label: 'Template', path: ['workflow', 'template'], input: 'select' as const, options: ['react_enterprise_qa', 'enterprise_qa'] },
  { label: 'Checkpointer Provider', path: ['workflow', 'checkpointer', 'provider'], input: 'select' as const, options: ['sqlite', 'memory'] },
  { label: 'Checkpointer URI', path: ['workflow', 'checkpointer', 'uri'], input: 'text' as const },
]
```

`module-configs/knowledge.ts`:
```typescript
export const KNOWLEDGE_FIELDS = [
  { label: 'Knowledge Provider', path: ['knowledge', 'provider'], input: 'select' as const, options: ['local_markdown', 'local_vector', 'remote_search', 'page_index'], description: 'The retrieval adapter for evidence chunks' },
  { label: 'Knowledge Path', path: ['knowledge', 'params', 'path'], input: 'text' as const, description: 'Path to knowledge source directory or file' },
  { label: 'Retrieval Strategy', path: ['retrieval', 'strategy'], input: 'select' as const, options: ['single_step', 'agentic_rag'] },
  { label: 'Top K', path: ['retrieval', 'top_k'], input: 'number' as const, description: 'Maximum chunks to retrieve' },
  { label: 'Min Score', path: ['retrieval', 'min_score'], input: 'number' as const, description: 'Minimum relevance score threshold' },
]
```

`module-configs/tools.ts`:
```typescript
export const TOOLS_FIELDS = [
  { label: 'Tools Config File', path: ['tools', 'file'], input: 'text' as const, description: 'Path to the tool contracts YAML file' },
]
```

`module-configs/policy.ts`:
```typescript
export const POLICY_FIELDS = [
  { label: 'Policy File', path: ['policy', 'file'], input: 'text' as const, description: 'Path to the policy rules YAML file' },
]
```

`module-configs/model.ts`:
```typescript
export const MODEL_FIELDS = [
  { label: 'Answer Model Provider', path: ['model', 'provider'], input: 'select' as const, options: ['deterministic', 'openai', 'anthropic', 'azure'], description: 'Provider for final answer generation' },
  { label: 'Answer Model Name', path: ['model', 'name'], input: 'text' as const, description: 'Model identifier for final answers' },
  { label: 'Max ReAct Steps', path: ['react', 'max_steps'], input: 'number' as const, description: 'Maximum planning and action steps per run' },
  { label: 'Max Tool Calls', path: ['react', 'max_tool_calls'], input: 'number' as const, description: 'Maximum governed tool calls per run' },
  { label: 'Record Reasoning', path: ['react', 'record_reasoning_summary'], input: 'select' as const, options: ['true', 'false'], description: 'Record structured reasoning summary' },
  { label: 'Planner Provider', path: ['react', 'planner', 'provider'], input: 'select' as const, options: ['deterministic', 'openai', 'anthropic'], description: 'Provider for ReAct planner' },
  { label: 'Planner Model', path: ['react', 'planner', 'name'], input: 'text' as const, description: 'Model name for ReAct planner' },
  { label: 'Review Mode', path: ['review', 'mode'], input: 'select' as const, options: ['auto', 'manual'], description: 'Harness review mode' },
  { label: 'Reviewer Provider', path: ['review', 'subagent', 'provider'], input: 'select' as const, options: ['deterministic', 'openai', 'anthropic'], description: 'Provider for review subagent' },
  { label: 'Reviewer Model', path: ['review', 'subagent', 'name'], input: 'text' as const, description: 'Model name for review subagent' },
  { label: 'Review Timeout (s)', path: ['review', 'subagent', 'timeout_seconds'], input: 'number' as const },
  { label: 'Review Fail Closed', path: ['review', 'subagent', 'fail_closed'], input: 'select' as const, options: ['true', 'false'] },
]
```

`module-configs/memory.ts`:
```typescript
export const MEMORY_FIELDS = [
  { label: 'Memory Provider', path: ['memory', 'provider'], input: 'select' as const, options: ['local', 'none'], description: 'Memory storage provider' },
  { label: 'Case Memory', path: ['memory', 'scopes', 'case', 'enabled'], input: 'select' as const, options: ['true', 'false'], description: 'Enable case-scoped memory' },
  { label: 'Case Retention (days)', path: ['memory', 'scopes', 'case', 'retention_days'], input: 'number' as const },
  { label: 'Case Max Records', path: ['memory', 'scopes', 'case', 'max_records'], input: 'number' as const },
  { label: 'Case Allow Restricted', path: ['memory', 'scopes', 'case', 'allow_restricted'], input: 'select' as const, options: ['true', 'false'] },
  { label: 'User Memory', path: ['memory', 'scopes', 'user', 'enabled'], input: 'select' as const, options: ['true', 'false'] },
  { label: 'Shared Memory', path: ['memory', 'scopes', 'shared', 'enabled'], input: 'select' as const, options: ['true', 'false'] },
]
```

`module-configs/response.ts`:
```typescript
export const RESPONSE_FIELDS = [
  { label: 'Include Reasoning Summary', path: ['response', 'include_reasoning_summary'], input: 'select' as const, options: ['true', 'false'], description: 'Show reasoning summary in response detail' },
  { label: 'Include Review Results', path: ['response', 'include_review_results'], input: 'select' as const, options: ['true', 'false'], description: 'Show review results in response detail' },
]
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/components/agent/module-configs/
git commit -m "feat: add field config definitions for all 7 configuration modules"
```

---

## Task 3: Wire Module Editors into AgentDetailPage

**Files:**
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`

- [ ] **Step 1: Update AgentDetailPage**

Add imports at the top:
```typescript
import { ModuleEditor } from '../components/agent/ModuleEditor'
import { WORKFLOW_FIELDS } from '../components/agent/module-configs/workflow'
import { KNOWLEDGE_FIELDS } from '../components/agent/module-configs/knowledge'
import { TOOLS_FIELDS } from '../components/agent/module-configs/tools'
import { POLICY_FIELDS } from '../components/agent/module-configs/policy'
import { MODEL_FIELDS } from '../components/agent/module-configs/model'
import { MEMORY_FIELDS } from '../components/agent/module-configs/memory'
import { RESPONSE_FIELDS } from '../components/agent/module-configs/response'
import { updateAgentYamlField } from '../utils/agentYaml'
```

Replace each placeholder tab with a ModuleEditor. Example for workflow:
```tsx
{activeTab === 'workflow' && (
  <ModuleEditor
    title="Workflow Configuration"
    description="Workflow runtime, template, and checkpointer settings"
    fields={WORKFLOW_FIELDS}
    yamlSection="workflow"
    agentYaml={agentYaml}
    onFieldChange={(path, value) => setAgentYaml((current) => updateAgentYamlField(current, path, value))}
    onSave={saveWorkflow}
    busy={busy === 'workflow'}
  />
)}
```

Repeat for each tab:
- `knowledge` → KNOWLEDGE_FIELDS, yamlSection="knowledge", description="Knowledge provider and retrieval settings"
- `tools` → TOOLS_FIELDS, yamlSection="tools"
- `policy` → POLICY_FIELDS, yamlSection="policy"
- `model` → MODEL_FIELDS, yamlSection="model", description="Model providers for answer, planner, and reviewer"
- `memory` → MEMORY_FIELDS, yamlSection="memory"
- `response` → RESPONSE_FIELDS, yamlSection="response"

- [ ] **Step 2: Run TypeScript check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/AgentDetailPage.tsx
git commit -m "feat: wire ModuleEditor into all 7 configuration tabs"
```

---

## Task 4: Verification

- [ ] **Step 1: Run all tests**

Run: `cd dashboard && npx vitest run`
Expected: All tests pass

- [ ] **Step 2: TypeScript check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Visual verification**

Run: `cd dashboard && npm run dev`

Verify:
- Click through all 8 CONFIGURE tabs
- Each tab shows form fields with current values
- "Show YAML" toggle shows the relevant YAML section
- Editing a field updates the form value
- "Save" button triggers the save action
- CONTRACT VIEW tab still shows full YAML

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: complete Phase 2 configuration modules"
```
