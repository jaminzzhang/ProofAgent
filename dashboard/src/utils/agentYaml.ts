export function updateAgentYamlField(
  agentYaml: string,
  path: string[],
  value: string,
): string {
  const lines = agentYaml.split('\n')
  const lineIndex = findYamlPathLineIndex(lines, path)
  if (lineIndex === -1) return insertYamlPath(lines, path, value).join('\n')

  const indent = (path.length - 1) * 2
  lines[lineIndex] = `${' '.repeat(indent)}${path[path.length - 1]}: ${formatYamlValue(value)}`
  return lines.join('\n')
}

export type AgentYamlMappingValue =
  | string
  | number
  | boolean
  | null
  | AgentYamlMapping

export interface AgentYamlMapping {
  [key: string]: AgentYamlMappingValue
}

export function replaceAgentYamlMapping(
  agentYaml: string,
  path: string[],
  value: AgentYamlMapping,
): string {
  const lines = agentYaml.split('\n')
  const lineIndex = findYamlPathLineIndex(lines, path)
  const rendered = renderYamlMapping(path[path.length - 1], value, (path.length - 1) * 2)

  if (lineIndex === -1) {
    if (path.length === 1) {
      return [...trimTrailingEmptyLines(lines), ...rendered].join('\n')
    }
    return updateAgentYamlField(agentYaml, path, '').split('\n').join('\n')
  }

  const indent = (path.length - 1) * 2
  const end = findBlockEnd(lines, lineIndex, indent)
  lines.splice(lineIndex, end - lineIndex, ...rendered)
  return lines.join('\n')
}

function insertYamlPath(lines: string[], path: string[], value: string): string[] {
  if (path.length === 0) return lines

  let start = 0
  let end = lines.length

  for (let depth = 0; depth < path.length; depth += 1) {
    const indent = depth * 2
    const lineIndex = findLineIndex(lines, indent, path[depth], start, end)
    if (lineIndex === -1) {
      if (depth === 0) return lines
      const insertedLines: string[] = []
      for (let missingDepth = depth; missingDepth < path.length - 1; missingDepth += 1) {
        insertedLines.push(`${' '.repeat(missingDepth * 2)}${path[missingDepth]}:`)
      }
      insertedLines.push(
        `${' '.repeat((path.length - 1) * 2)}${path[path.length - 1]}: ${formatYamlValue(value)}`,
      )
      lines.splice(end, 0, ...insertedLines)
      return lines
    }

    start = lineIndex + 1
    end = findBlockEnd(lines, lineIndex, indent)
  }

  return lines
}

function renderYamlMapping(key: string, value: AgentYamlMapping, indent: number): string[] {
  return [`${' '.repeat(indent)}${key}:`, ...renderYamlObject(value, indent + 2)]
}

function renderYamlObject(value: AgentYamlMapping, indent: number): string[] {
  const lines: string[] = []
  for (const [key, item] of Object.entries(value)) {
    if (item === undefined || item === null || item === '') continue
    if (isPlainObject(item)) {
      const childLines = renderYamlObject(item, indent + 2)
      if (childLines.length === 0) continue
      lines.push(`${' '.repeat(indent)}${key}:`)
      lines.push(...childLines)
    } else {
      lines.push(`${' '.repeat(indent)}${key}: ${formatYamlValue(String(item))}`)
    }
  }
  return lines
}

function isPlainObject(value: unknown): value is AgentYamlMapping {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function trimTrailingEmptyLines(lines: string[]): string[] {
  const copy = [...lines]
  while (copy.length > 0 && copy[copy.length - 1] === '') copy.pop()
  return copy
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
    if (line.trim() && indentation(line) <= indent) {
      if (line.trim().startsWith('-')) continue
      return index
    }
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
