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

export interface AgentYamlWorkflowNodePrompt {
  business_context?: string | null
  task_instructions: string[]
  output_preferences: string[]
}

export interface AgentYamlWorkflowNodeConfig {
  node_id: string
  prompt: AgentYamlWorkflowNodePrompt
  context: Record<string, boolean>
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

export function readWorkflowTemplateDescriptorVersion(agentYaml: string): string {
  return readAgentYamlField(agentYaml, ['workflow', 'template_descriptor_version'])
}

export function readWorkflowNodeConfigs(agentYaml: string): AgentYamlWorkflowNodeConfig[] {
  const lines = agentYaml.split('\n')
  const workflowStart = findLineIndex(lines, 0, 'workflow')
  if (workflowStart === -1) return []

  const workflowEnd = findBlockEnd(lines, workflowStart, 0)
  const nodesIndex = findLineIndex(lines, 2, 'nodes', workflowStart + 1, workflowEnd)
  if (nodesIndex === -1) return []

  const nodesEnd = findBlockEnd(lines, nodesIndex, 2)
  const nodes: AgentYamlWorkflowNodeConfig[] = []
  const itemPattern = /^(\s*)-\s+node_id:\s*(.*)$/
  let index = nodesIndex + 1
  while (index < nodesEnd) {
    const line = lines[index]
    const match = line.match(itemPattern)
    if (!match) {
      index += 1
      continue
    }

    const nodeStart = index
    const nodeIndent = match[1].length
    index += 1
    while (index < nodesEnd) {
      const nextMatch = lines[index].match(itemPattern)
      if (nextMatch && nextMatch[1].length === nodeIndent) break
      index += 1
    }
    nodes.push(parseWorkflowNodeBlock(lines.slice(nodeStart, index), match[2]))
  }

  return nodes
}

export function replaceWorkflowNodes(
  agentYaml: string,
  templateDescriptorVersion: string | null | undefined,
  nodes: AgentYamlWorkflowNodeConfig[],
): string {
  const lines = agentYaml.split('\n')
  let workflowStart = findLineIndex(lines, 0, 'workflow')
  if (workflowStart === -1) {
    const rendered = renderWorkflowSection(templateDescriptorVersion, nodes)
    return [...trimTrailingEmptyLines(lines), ...rendered].join('\n')
  }

  let workflowEnd = findBlockEnd(lines, workflowStart, 0)
  if (templateDescriptorVersion) {
    const versionLine = findLineIndex(
      lines,
      2,
      'template_descriptor_version',
      workflowStart + 1,
      workflowEnd,
    )
    if (versionLine === -1) {
      lines.splice(workflowStart + 1, 0, `  template_descriptor_version: ${formatYamlValue(templateDescriptorVersion)}`)
      workflowEnd += 1
    } else {
      lines[versionLine] = `  template_descriptor_version: ${formatYamlValue(templateDescriptorVersion)}`
    }
  }

  const renderedNodes = renderWorkflowNodes(nodes)
  const nodesIndex = findLineIndex(lines, 2, 'nodes', workflowStart + 1, workflowEnd)
  if (nodesIndex === -1) {
    lines.splice(workflowEnd, 0, ...renderedNodes)
  } else {
    const nodesEnd = findBlockEnd(lines, nodesIndex, 2)
    lines.splice(nodesIndex, nodesEnd - nodesIndex, ...renderedNodes)
  }
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

function renderWorkflowSection(
  templateDescriptorVersion: string | null | undefined,
  nodes: AgentYamlWorkflowNodeConfig[],
): string[] {
  const lines = ['workflow:']
  if (templateDescriptorVersion) {
    lines.push(`  template_descriptor_version: ${formatYamlValue(templateDescriptorVersion)}`)
  }
  lines.push(...renderWorkflowNodes(nodes))
  return lines
}

function renderWorkflowNodes(nodes: AgentYamlWorkflowNodeConfig[]): string[] {
  const lines = ['  nodes:']
  for (const node of nodes) {
    lines.push(`    - node_id: ${formatYamlValue(node.node_id)}`)
    const promptLines = renderWorkflowNodePrompt(node.prompt)
    if (promptLines.length > 0) {
      lines.push('      prompt:')
      lines.push(...promptLines)
    }
    const contextEntries = Object.entries(node.context).filter(([, value]) => value)
    if (contextEntries.length > 0) {
      lines.push('      context:')
      for (const [key, value] of contextEntries) {
        lines.push(`        ${key}: ${formatYamlValue(String(value))}`)
      }
    }
  }
  return lines
}

function renderWorkflowNodePrompt(prompt: AgentYamlWorkflowNodePrompt): string[] {
  const lines: string[] = []
  if (prompt.business_context?.trim()) {
    lines.push(`        business_context: ${formatYamlValue(prompt.business_context)}`)
  }
  if (prompt.task_instructions.length > 0) {
    lines.push('        task_instructions:')
    for (const instruction of prompt.task_instructions.filter((item) => item.trim())) {
      lines.push(`          - ${formatYamlValue(instruction)}`)
    }
  }
  if (prompt.output_preferences.length > 0) {
    lines.push('        output_preferences:')
    for (const preference of prompt.output_preferences.filter((item) => item.trim())) {
      lines.push(`          - ${formatYamlValue(preference)}`)
    }
  }
  return lines
}

function parseWorkflowNodeBlock(
  blockLines: string[],
  nodeIdValue: string,
): AgentYamlWorkflowNodeConfig {
  const nodeIndent = indentation(blockLines[0] ?? '')
  const fieldIndent = nodeIndent + 4
  const listIndent = nodeIndent + 6
  const prompt: AgentYamlWorkflowNodePrompt = {
    business_context: '',
    task_instructions: [],
    output_preferences: [],
  }
  const context: Record<string, boolean> = {}

  for (let index = 1; index < blockLines.length; index += 1) {
    const line = blockLines[index]
    const promptScalar = line.match(
      new RegExp(`^\\s{${fieldIndent}}business_context:\\s*(.*)$`),
    )
    if (promptScalar) {
      prompt.business_context = parseInlineYamlValue(promptScalar[1])
      continue
    }

    const instruction = line.match(
      new RegExp(`^\\s{${fieldIndent},${listIndent}}-\\s*(.*)$`),
    )
    if (instruction && isInsideList(blockLines, index, 'task_instructions', fieldIndent)) {
      prompt.task_instructions.push(parseInlineYamlValue(instruction[1]))
      continue
    }
    if (instruction && isInsideList(blockLines, index, 'output_preferences', fieldIndent)) {
      prompt.output_preferences.push(parseInlineYamlValue(instruction[1]))
      continue
    }

    const contextEntry = line.match(
      new RegExp(`^\\s{${fieldIndent}}([A-Za-z0-9_]+):\\s*(true|false)$`),
    )
    if (contextEntry && isInsideMapping(blockLines, index, 'context', nodeIndent + 2)) {
      context[contextEntry[1]] = contextEntry[2] === 'true'
    }
  }

  return {
    node_id: parseInlineYamlValue(nodeIdValue),
    prompt,
    context,
  }
}

function isInsideList(
  blockLines: string[],
  index: number,
  key: string,
  fieldIndent: number,
): boolean {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (new RegExp(`^\\s{${fieldIndent}}[A-Za-z0-9_]+:`).test(blockLines[cursor])) {
      return blockLines[cursor].trim() === `${key}:`
    }
  }
  return false
}

function isInsideMapping(
  blockLines: string[],
  index: number,
  key: string,
  sectionIndent: number,
): boolean {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (new RegExp(`^\\s{${sectionIndent}}[A-Za-z0-9_]+:`).test(blockLines[cursor])) {
      return blockLines[cursor].trim() === `${key}:`
    }
  }
  return false
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
  return parseInlineYamlValue(value)
}

function parseInlineYamlValue(value: string): string {
  const trimmed = value.trim()
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1)
  }
  return trimmed
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
