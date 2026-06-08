export const MEMORY_FIELDS = [
  {
    label: 'Memory Provider',
    path: ['memory', 'provider'],
    input: 'select' as const,
    options: ['session', 'local', 'mem0'],
    description: 'Controls where admitted memory records are stored between runs.',
  },
  {
    label: 'Case Memory',
    path: ['memory', 'scopes', 'case', 'enabled'],
    input: 'select' as const,
    options: ['true', 'false'],
    description: 'Lets the Agent reuse facts from the current case while keeping them out of broader user or shared memory.',
  },
  {
    label: 'Case Retention (days)',
    path: ['memory', 'scopes', 'case', 'retention_days'],
    input: 'number' as const,
    description: 'Sets how long case-scoped memory remains eligible for retrieval.',
  },
  {
    label: 'Case Max Records',
    path: ['memory', 'scopes', 'case', 'max_records'],
    input: 'number' as const,
    description: 'Caps how many case memory records can be returned to the Agent context.',
  },
  {
    label: 'Case Allow Restricted',
    path: ['memory', 'scopes', 'case', 'allow_restricted'],
    input: 'select' as const,
    options: ['true', 'false'],
    description: 'Controls whether restricted memory can be admitted into case context.',
  },
  {
    label: 'User Memory',
    path: ['memory', 'scopes', 'user', 'enabled'],
    input: 'select' as const,
    options: ['true', 'false'],
    description: 'Enables longer-lived user-scoped memory across cases for the same user identity.',
  },
  {
    label: 'Shared Memory',
    path: ['memory', 'scopes', 'shared', 'enabled'],
    input: 'select' as const,
    options: ['true', 'false'],
    description: 'Enables shared memory that can influence more than one user or case.',
  },
]
