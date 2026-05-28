export const MEMORY_FIELDS = [
  { label: 'Memory Provider', path: ['memory', 'provider'], input: 'select' as const, options: ['session', 'local', 'mem0'], description: 'Memory storage provider' },
  { label: 'Case Memory', path: ['memory', 'scopes', 'case', 'enabled'], input: 'select' as const, options: ['true', 'false'], description: 'Enable case-scoped memory' },
  { label: 'Case Retention (days)', path: ['memory', 'scopes', 'case', 'retention_days'], input: 'number' as const },
  { label: 'Case Max Records', path: ['memory', 'scopes', 'case', 'max_records'], input: 'number' as const },
  { label: 'Case Allow Restricted', path: ['memory', 'scopes', 'case', 'allow_restricted'], input: 'select' as const, options: ['true', 'false'] },
  { label: 'User Memory', path: ['memory', 'scopes', 'user', 'enabled'], input: 'select' as const, options: ['true', 'false'] },
  { label: 'Shared Memory', path: ['memory', 'scopes', 'shared', 'enabled'], input: 'select' as const, options: ['true', 'false'] },
]
