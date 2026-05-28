export interface WorkflowNodeField {
  label: string
  path: string[]
  value: string
  input: 'text' | 'number'
}

export interface WorkflowNodeConfig {
  id: string
  label: string
  fields: WorkflowNodeField[]
}

export function buildWorkflowNodes(agentYaml: string): WorkflowNodeConfig[] {
  return [
    {
      id: 'workflow',
      label: 'Workflow',
      fields: [
        field(agentYaml, 'Runtime', ['workflow', 'runtime']),
        field(agentYaml, 'Template', ['workflow', 'template']),
        field(agentYaml, 'Checkpointer', ['workflow', 'checkpointer', 'provider']),
      ],
    },
    {
      id: 'knowledge',
      label: 'Knowledge',
      fields: [
        field(agentYaml, 'Provider', ['knowledge', 'provider']),
        field(agentYaml, 'Path', ['knowledge', 'params', 'path']),
      ],
    },
    {
      id: 'retrieval',
      label: 'Retrieval',
      fields: [
        field(agentYaml, 'Strategy', ['retrieval', 'strategy']),
        field(agentYaml, 'Top K', ['retrieval', 'top_k'], 'number'),
        field(agentYaml, 'Min Score', ['retrieval', 'min_score'], 'number'),
      ],
    },
    {
      id: 'model',
      label: 'Model',
      fields: [
        field(agentYaml, 'Provider', ['model', 'provider']),
        field(agentYaml, 'Name', ['model', 'name']),
      ],
    },
    {
      id: 'policy',
      label: 'Policy',
      fields: [field(agentYaml, 'File', ['policy', 'file'])],
    },
    {
      id: 'tools',
      label: 'Tools',
      fields: [field(agentYaml, 'File', ['tools', 'file'])],
    },
  ]
}

export function updateAgentYamlField(
  agentYaml: string,
  path: string[],
  value: string,
): string {
  const lines = agentYaml.split('\n')
  const lineIndex = findYamlPathLineIndex(lines, path)
  if (lineIndex === -1) return agentYaml

  const indent = (path.length - 1) * 2
  lines[lineIndex] = `${' '.repeat(indent)}${path[path.length - 1]}: ${formatYamlValue(value)}`
  return lines.join('\n')
}

function field(
  agentYaml: string,
  label: string,
  path: string[],
  input: 'text' | 'number' = 'text',
): WorkflowNodeField {
  return {
    label,
    path,
    value: readYamlScalar(agentYaml, path),
    input,
  }
}

function readYamlScalar(agentYaml: string, path: string[]): string {
  return readAgentYamlField(agentYaml, path)
}

export function readAgentYamlField(agentYaml: string, path: string[]): string {
  const lines = agentYaml.split('\n')
  const lineIndex = findYamlPathLineIndex(lines, path)
  if (lineIndex === -1) return ''
  return parseYamlValue(lines[lineIndex])
}

export function extractAgentYamlSection(
  agentYaml: string,
  sectionName: string,
): string {
  const lines = agentYaml.split('\n')
  const start = findLineIndex(lines, 0, sectionName)
  if (start === -1) return ''
  return lines.slice(start, findBlockEnd(lines, start, 0)).join('\n')
}

function findLineIndex(
  lines: string[],
  indent: number,
  key: string,
  start = 0,
  end = lines.length,
): number {
  const pattern = new RegExp(`^${' '.repeat(indent)}${escapeRegExp(key)}:\\s*(.*)$`)
  for (let index = start; index < end; index += 1) {
    if (pattern.test(lines[index])) return index
  }
  return -1
}

function findYamlPathLineIndex(lines: string[], path: string[]): number {
  if (path.length === 0) return -1

  let start = 0
  let end = lines.length
  let lineIndex = -1

  for (let depth = 0; depth < path.length; depth += 1) {
    const indent = depth * 2
    lineIndex = findLineIndex(lines, indent, path[depth], start, end)
    if (lineIndex === -1) return -1
    start = lineIndex + 1
    end = findBlockEnd(lines, lineIndex, indent)
  }

  return lineIndex
}

function findBlockEnd(lines: string[], start: number, indent: number): number {
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index]
    if (line.trim() && indentation(line) <= indent) return index
  }
  return lines.length
}

function indentation(line: string): number {
  return line.length - line.trimStart().length
}

function parseYamlValue(line: string): string {
  const value = line.slice(line.indexOf(':') + 1).trim()
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    return value.slice(1, -1)
  }
  return value
}

function formatYamlValue(value: string): string {
  const trimmed = value.trim()
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return trimmed
  if (trimmed === 'true' || trimmed === 'false') return trimmed
  if (trimmed.startsWith('./') || /^[\w./-]+$/.test(trimmed)) return trimmed
  return JSON.stringify(value)
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
