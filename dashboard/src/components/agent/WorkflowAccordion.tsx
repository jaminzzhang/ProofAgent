import { useState } from 'react'
import type { WorkflowNodeConfig } from '../../utils/agentYaml'

interface WorkflowAccordionProps {
  nodes: WorkflowNodeConfig[]
  selectedNodeId: string
  onSelectNode: (nodeId: string) => void
  onFieldChange: (nodeId: string, path: string[], value: string) => void
}

export function WorkflowAccordion({
  nodes,
  selectedNodeId,
  onSelectNode,
  onFieldChange,
}: WorkflowAccordionProps) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg">
      <div className="flex flex-wrap items-center gap-1 border-b border-[var(--border)] px-4 py-3">
        {nodes.map((node, i) => (
          <span key={node.id} className="flex items-center gap-1">
            <button
              onClick={() => onSelectNode(node.id)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                node.id === selectedNodeId
                  ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
              }`}
            >
              {node.label}
            </button>
            {i < nodes.length - 1 && (
              <svg className="h-3 w-3 text-[var(--text-muted)] shrink-0" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 4l4 4-4 4" />
              </svg>
            )}
          </span>
        ))}
      </div>
      <div>
        {nodes.map((node) => (
          <NodeEditor
            key={node.id}
            node={node}
            isExpanded={node.id === selectedNodeId}
            onToggle={() => onSelectNode(node.id)}
            onFieldChange={onFieldChange}
          />
        ))}
      </div>
    </div>
  )
}

interface NodeEditorProps {
  node: WorkflowNodeConfig
  isExpanded: boolean
  onToggle: () => void
  onFieldChange: (nodeId: string, path: string[], value: string) => void
}

function NodeEditor({ node, isExpanded, onToggle, onFieldChange }: NodeEditorProps) {
  const [localValues, setLocalValues] = useState<Record<string, string>>(
    Object.fromEntries(node.fields.map((f) => [f.path.join('.'), f.value])),
  )

  const previews = node.fields.slice(0, 2).map((f) => f.value)

  const handleChange = (path: string[], value: string) => {
    setLocalValues((prev) => ({ ...prev, [path.join('.')]: value }))
    onFieldChange(node.id, path, value)
  }

  return (
    <div className={isExpanded ? 'bg-[var(--bg-elevated)]' : ''}>
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-[var(--bg-hover)] transition-colors"
      >
        <svg
          className={`h-4 w-4 text-[var(--text-muted)] shrink-0 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
          viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
        >
          <path d="M6 4l4 4-4 4" />
        </svg>
        <span className="text-sm font-medium text-[var(--text-primary)]">{node.label}</span>
        {!isExpanded && (
          <span className="ml-auto text-xs text-[var(--text-muted)] truncate max-w-[200px]">
            {previews.join(' / ')}
          </span>
        )}
      </button>
      {isExpanded && (
        <div className="border-t border-[var(--border)] px-4 py-3 space-y-3">
          {node.fields.map((field) => (
            <div key={field.path.join('.')} className="flex items-center gap-3">
              <label className="w-36 shrink-0 text-xs font-medium text-[var(--text-secondary)]">
                {field.label}
              </label>
              <input
                type={field.input}
                value={localValues[field.path.join('.')] ?? field.value}
                onChange={(e) => handleChange(field.path, e.target.value)}
                className="flex-1 bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
