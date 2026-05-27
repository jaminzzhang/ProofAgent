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
  if (path.length === 1) {
    return replaceLine(agentYaml, 0, path[0], value)
  }
  if (path.length === 2) {
    return replaceNestedLine(agentYaml, path[0], 2, path[1], value)
  }
  if (path.length === 3) {
    const section = extractSection(agentYaml, path[0])
    if (!section) return agentYaml
    const parentRange = findLineRange(section.lines, 2, path[1])
    if (!parentRange) return agentYaml
    const lineIndex = findLineIndex(section.lines, 4, path[2], parentRange.start + 1, parentRange.end)
    if (lineIndex === -1) return agentYaml
    const lines = agentYaml.split('\n')
    lines[section.start + lineIndex] = `${' '.repeat(4)}${path[2]}: ${formatYamlValue(value)}`
    return lines.join('\n')
  }
  return agentYaml
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
  if (path.length === 1) {
    return readLineValue(agentYaml.split('\n'), 0, path[0])
  }
  const section = extractSection(agentYaml, path[0])
  if (!section) return ''
  if (path.length === 2) {
    return readLineValue(section.lines, 2, path[1])
  }
  const parentRange = findLineRange(section.lines, 2, path[1])
  if (!parentRange) return ''
  const lineIndex = findLineIndex(section.lines, 4, path[2], parentRange.start + 1, parentRange.end)
  if (lineIndex === -1) return ''
  return parseYamlValue(section.lines[lineIndex])
}

function replaceLine(agentYaml: string, indent: number, key: string, value: string): string {
  const lines = agentYaml.split('\n')
  const lineIndex = findLineIndex(lines, indent, key)
  if (lineIndex === -1) return agentYaml
  lines[lineIndex] = `${' '.repeat(indent)}${key}: ${formatYamlValue(value)}`
  return lines.join('\n')
}

function replaceNestedLine(
  agentYaml: string,
  sectionName: string,
  indent: number,
  key: string,
  value: string,
): string {
  const section = extractSection(agentYaml, sectionName)
  if (!section) return agentYaml
  const lineIndex = findLineIndex(section.lines, indent, key)
  if (lineIndex === -1) return agentYaml
  const lines = agentYaml.split('\n')
  lines[section.start + lineIndex] = `${' '.repeat(indent)}${key}: ${formatYamlValue(value)}`
  return lines.join('\n')
}

function extractSection(
  agentYaml: string,
  sectionName: string,
): { start: number; lines: string[] } | null {
  const lines = agentYaml.split('\n')
  const start = findLineIndex(lines, 0, sectionName)
  if (start === -1) return null
  let end = lines.length
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index]
    if (line.trim() && !line.startsWith(' ')) {
      end = index
      break
    }
  }
  return { start, lines: lines.slice(start, end) }
}

function readLineValue(lines: string[], indent: number, key: string): string {
  const lineIndex = findLineIndex(lines, indent, key)
  if (lineIndex === -1) return ''
  return parseYamlValue(lines[lineIndex])
}

function findLineRange(
  lines: string[],
  indent: number,
  key: string,
): { start: number; end: number } | null {
  const start = findLineIndex(lines, indent, key)
  if (start === -1) return null
  let end = lines.length
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index]
    if (line.trim() && line.startsWith(' '.repeat(indent)) && !line.startsWith(' '.repeat(indent + 2))) {
      end = index
      break
    }
  }
  return { start, end }
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
