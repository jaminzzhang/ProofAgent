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

export interface AgentYamlWorkflowStagePrompt {
  business_context?: string | null
  task_instructions: string[]
  output_preferences: string[]
}

export interface AgentYamlWorkflowStageConfig {
  id: string
  prompt: AgentYamlWorkflowStagePrompt
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
    const parentPath = path.slice(0, -1)
    const parentIndex = findYamlPathLineIndex(lines, parentPath)
    if (parentIndex !== -1) {
      const parentIndent = (parentPath.length - 1) * 2
      const parentEnd = findBlockEnd(lines, parentIndex, parentIndent)
      lines.splice(parentEnd, 0, ...rendered)
      return lines.join('\n')
    }
    return [...trimTrailingEmptyLines(lines), ...renderNestedYamlMapping(path, value, 0)].join('\n')
  }

  const indent = (path.length - 1) * 2
  const end = findBlockEnd(lines, lineIndex, indent)
  lines.splice(lineIndex, end - lineIndex, ...rendered)
  return lines.join('\n')
}

export function replaceMemoryCapabilityConfiguration(
  agentYaml: string,
  changedPath: string[],
  changedValue: string,
): string {
  const normalizedYaml = removeTopLevelYamlSection(agentYaml, 'memory')
  const changedEnabled = samePath(changedPath, ['capabilities', 'memory', 'enabled'])
  if (changedEnabled && changedValue === 'false') {
    return replaceAgentYamlMapping(normalizedYaml, ['capabilities', 'memory'], {
      enabled: false,
    })
  }
  const changedUserEnabled = samePath(
    changedPath,
    ['capabilities', 'memory', 'scopes', 'user', 'enabled'],
  )
  const hasCanonicalMemory = Boolean(
    extractAgentYamlPathSection(normalizedYaml, ['capabilities', 'memory']),
  )
  if (
    hasCanonicalMemory &&
    !(changedEnabled && changedValue === 'true') &&
    !(changedUserEnabled && changedValue === 'true')
  ) {
    return updateAgentYamlField(normalizedYaml, changedPath, changedValue)
  }

  const readOrChanged = (path: string[], fallback: string): string => {
    if (samePath(path, changedPath)) return changedValue || fallback
    return readAgentYamlField(normalizedYaml, path) || fallback
  }
  const boolOrChanged = (path: string[], fallback: boolean): boolean =>
    readOrChanged(path, fallback ? 'true' : 'false') === 'true'

  const memoryConfig: AgentYamlMapping = {
    enabled: boolOrChanged(['capabilities', 'memory', 'enabled'], true),
    provider: readOrChanged(['capabilities', 'memory', 'provider'], 'session'),
    scopes: {
      case: {
        enabled: boolOrChanged(
          ['capabilities', 'memory', 'scopes', 'case', 'enabled'],
          false,
        ),
        retention_days: readOrChanged(
          ['capabilities', 'memory', 'scopes', 'case', 'retention_days'],
          '30',
        ),
        max_records: readOrChanged(
          ['capabilities', 'memory', 'scopes', 'case', 'max_records'],
          '5',
        ),
        allow_restricted: boolOrChanged(
          ['capabilities', 'memory', 'scopes', 'case', 'allow_restricted'],
          false,
        ),
      },
      user: {
        enabled: boolOrChanged(
          ['capabilities', 'memory', 'scopes', 'user', 'enabled'],
          false,
        ),
        retention_days: readOrChanged(
          ['capabilities', 'memory', 'scopes', 'user', 'retention_days'],
          '30',
        ),
        max_records: readOrChanged(
          ['capabilities', 'memory', 'scopes', 'user', 'max_records'],
          '5',
        ),
        allow_restricted: boolOrChanged(
          ['capabilities', 'memory', 'scopes', 'user', 'allow_restricted'],
          false,
        ),
      },
      shared: {
        enabled: boolOrChanged(
          ['capabilities', 'memory', 'scopes', 'shared', 'enabled'],
          false,
        ),
      },
    },
  }

  return replaceAgentYamlMapping(normalizedYaml, ['capabilities', 'memory'], memoryConfig)
}

export function replaceAgentContextConfiguration(
  agentYaml: string,
  changedPath: string[],
  changedValue: string,
): string {
  const normalizedYaml = removeTopLevelYamlSection(agentYaml, 'memory')
  const changedGroup = agentContextConfigurationGroup(changedPath)
  if (!changedGroup) return updateAgentYamlField(normalizedYaml, changedPath, changedValue)

  const readOrChanged = (path: string[], fallback: string): string => {
    if (samePath(path, changedPath)) return changedValue || fallback
    return readAgentYamlField(normalizedYaml, path) || fallback
  }
  const boolOrChanged = (path: string[], fallback: boolean): boolean =>
    readOrChanged(path, fallback ? 'true' : 'false') === 'true'
  const maxTokensPath = ['context', 'budget_profile', 'max_tokens']
  const reservedOutputTokensPath = ['context', 'budget_profile', 'reserved_output_tokens']
  const budgetValues = [
    samePath(changedPath, maxTokensPath)
      ? changedValue.trim()
      : readAgentYamlField(normalizedYaml, maxTokensPath),
    samePath(changedPath, reservedOutputTokensPath)
      ? changedValue.trim()
      : readAgentYamlField(normalizedYaml, reservedOutputTokensPath),
  ]
  const hasBudgetOverride = budgetValues.some(Boolean)

  const recallConfig: AgentYamlMapping = {
    source_policies: {
      memory_recall: {
        scopes: {
          case: {
            enabled: boolOrChanged(
              ['context', 'source_policies', 'memory_recall', 'scopes', 'case', 'enabled'],
              true,
            ),
          },
          user: {
            enabled: boolOrChanged(
              ['context', 'source_policies', 'memory_recall', 'scopes', 'user', 'enabled'],
              false,
            ),
          },
          shared: {
            enabled: boolOrChanged(
              ['context', 'source_policies', 'memory_recall', 'scopes', 'shared', 'enabled'],
              false,
            ),
          },
        },
      },
    },
  }
  const budgetProfile: AgentYamlMapping = {
    max_tokens: readOrChanged(maxTokensPath, '8192'),
    reserved_output_tokens: readOrChanged(reservedOutputTokensPath, '0'),
    estimation_strategy: 'heuristic',
    profile_version: 'context_budget.v1',
  }
  const includeBudget = changedGroup === 'budget' && hasBudgetOverride
  const includeRecall = changedGroup === 'recall'

  const contextConfig: AgentYamlMapping = {}
  if (includeRecall) {
    contextConfig.source_policies = recallConfig.source_policies
  }
  if (includeBudget) {
    contextConfig.budget_profile = budgetProfile
  }
  if (Object.keys(contextConfig).length === 0) {
    return changedGroup === 'budget'
      ? removeYamlPathSection(normalizedYaml, ['context', 'budget_profile'])
      : normalizedYaml
  }

  if (!extractAgentYamlSection(normalizedYaml, 'context')) {
    return replaceAgentYamlMapping(normalizedYaml, ['context'], contextConfig)
  }

  const memoryRecall = (recallConfig.source_policies as AgentYamlMapping)
    .memory_recall as AgentYamlMapping
  const memoryRecallScopes = memoryRecall.scopes as AgentYamlMapping
  const caseRecall = memoryRecallScopes.case as AgentYamlMapping
  const userRecall = memoryRecallScopes.user as AgentYamlMapping
  const sharedRecall = memoryRecallScopes.shared as AgentYamlMapping

  const fields: Array<[string[], string]> = []
  if (includeRecall) {
    fields.push([
      ['context', 'source_policies', 'memory_recall', 'scopes', 'case', 'enabled'],
      String(caseRecall.enabled),
    ])
    fields.push([
      ['context', 'source_policies', 'memory_recall', 'scopes', 'user', 'enabled'],
      String(userRecall.enabled),
    ])
    fields.push([
      ['context', 'source_policies', 'memory_recall', 'scopes', 'shared', 'enabled'],
      String(sharedRecall.enabled),
    ])
  }
  if (includeBudget) {
    fields.push([
      ['context', 'budget_profile', 'max_tokens'],
      String(budgetProfile.max_tokens),
    ])
    fields.push([
      ['context', 'budget_profile', 'reserved_output_tokens'],
      String(budgetProfile.reserved_output_tokens),
    ])
    fields.push(['context.budget_profile.estimation_strategy'.split('.'), 'heuristic'])
    fields.push(['context.budget_profile.profile_version'.split('.'), 'context_budget.v1'])
  }

  return fields.reduce(
    (current, [path, value]) => updateAgentYamlField(current, path, value),
    normalizedYaml,
  )
}

export function readWorkflowTemplateDescriptorVersion(agentYaml: string): string {
  return readAgentYamlField(agentYaml, ['workflow', 'template_descriptor_version'])
}

export function readWorkflowStageConfigs(agentYaml: string): AgentYamlWorkflowStageConfig[] {
  const lines = agentYaml.split('\n')
  const workflowStart = findLineIndex(lines, 0, 'workflow')
  if (workflowStart === -1) return []

  const workflowEnd = findBlockEnd(lines, workflowStart, 0)
  const stagesIndex = findLineIndex(lines, 2, 'stages', workflowStart + 1, workflowEnd)
  if (stagesIndex === -1) return []

  const stagesEnd = findBlockEnd(lines, stagesIndex, 2)
  const stages: AgentYamlWorkflowStageConfig[] = []
  const itemPattern = /^(\s*)-\s+id:\s*(.*)$/
  let index = stagesIndex + 1
  while (index < stagesEnd) {
    const line = lines[index]
    const match = line.match(itemPattern)
    if (!match) {
      index += 1
      continue
    }

    const nodeStart = index
    const nodeIndent = match[1].length
    index += 1
    while (index < stagesEnd) {
      const nextMatch = lines[index].match(itemPattern)
      if (nextMatch && nextMatch[1].length === nodeIndent) break
      index += 1
    }
    stages.push(parseWorkflowStageBlock(lines.slice(nodeStart, index), match[2]))
  }

  return stages
}

export function replaceWorkflowStages(
  agentYaml: string,
  templateDescriptorVersion: string | null | undefined,
  stages: AgentYamlWorkflowStageConfig[],
): string {
  const lines = agentYaml.split('\n')
  let workflowStart = findLineIndex(lines, 0, 'workflow')
  if (workflowStart === -1) {
    const rendered = renderWorkflowSection(templateDescriptorVersion, stages)
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

  const renderedStages = renderWorkflowStages(stages)
  const stagesIndex = findLineIndex(lines, 2, 'stages', workflowStart + 1, workflowEnd)
  if (stagesIndex === -1) {
    lines.splice(workflowEnd, 0, ...renderedStages)
  } else {
    const stagesEnd = findBlockEnd(lines, stagesIndex, 2)
    lines.splice(stagesIndex, stagesEnd - stagesIndex, ...renderedStages)
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

function renderNestedYamlMapping(
  path: string[],
  value: AgentYamlMapping,
  indent: number,
): string[] {
  if (path.length === 1) return renderYamlMapping(path[0], value, indent)
  return [
    `${' '.repeat(indent)}${path[0]}:`,
    ...renderNestedYamlMapping(path.slice(1), value, indent + 2),
  ]
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
  stages: AgentYamlWorkflowStageConfig[],
): string[] {
  const lines = ['workflow:']
  if (templateDescriptorVersion) {
    lines.push(`  template_descriptor_version: ${formatYamlValue(templateDescriptorVersion)}`)
  }
  lines.push(...renderWorkflowStages(stages))
  return lines
}

function renderWorkflowStages(stages: AgentYamlWorkflowStageConfig[]): string[] {
  const lines = ['  stages:']
  for (const stage of stages) {
    lines.push(`    - id: ${formatYamlValue(stage.id)}`)
    const promptLines = renderWorkflowStagePrompt(stage.prompt)
    if (promptLines.length > 0) {
      lines.push('      prompt:')
      lines.push(...promptLines)
    }
    const contextEntries = Object.entries(stage.context).filter(([, value]) => value)
    if (contextEntries.length > 0) {
      lines.push('      context:')
      for (const [key, value] of contextEntries) {
        lines.push(`        ${key}: ${formatYamlValue(String(value))}`)
      }
    }
  }
  return lines
}

function renderWorkflowStagePrompt(prompt: AgentYamlWorkflowStagePrompt): string[] {
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

function parseWorkflowStageBlock(
  blockLines: string[],
  nodeIdValue: string,
): AgentYamlWorkflowStageConfig {
  const nodeIndent = indentation(blockLines[0] ?? '')
  const fieldIndent = nodeIndent + 4
  const listIndent = nodeIndent + 6
  const prompt: AgentYamlWorkflowStagePrompt = {
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
    id: parseInlineYamlValue(nodeIdValue),
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

function samePath(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((segment, index) => segment === right[index])
}

function startsWithPath(path: string[], prefix: string[]): boolean {
  return prefix.every((segment, index) => path[index] === segment)
}

function agentContextConfigurationGroup(
  path: string[],
): 'recall' | 'budget' | null {
  if (startsWithPath(path, ['context', 'source_policies', 'memory_recall'])) return 'recall'
  if (startsWithPath(path, ['context', 'budget_profile'])) return 'budget'
  return null
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

function extractAgentYamlPathSection(agentYaml: string, path: string[]): string {
  const lines = agentYaml.split('\n')
  const start = findYamlPathLineIndex(lines, path)
  if (start === -1) return ''
  return lines.slice(start, findBlockEnd(lines, start, (path.length - 1) * 2)).join('\n')
}

function removeTopLevelYamlSection(agentYaml: string, sectionName: string): string {
  const lines = agentYaml.split('\n')
  const start = findLineIndex(lines, 0, sectionName)
  if (start === -1) return agentYaml
  lines.splice(start, findBlockEnd(lines, start, 0) - start)
  return lines.join('\n')
}

function removeYamlPathSection(agentYaml: string, path: string[]): string {
  const lines = agentYaml.split('\n')
  const start = findYamlPathLineIndex(lines, path)
  if (start === -1) return agentYaml
  lines.splice(start, findBlockEnd(lines, start, (path.length - 1) * 2) - start)
  return lines.join('\n')
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
