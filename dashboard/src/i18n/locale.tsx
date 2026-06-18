import { createContext, useContext, useEffect, useMemo, useState } from 'react'

export type Locale = 'en-US' | 'zh-CN'

const LOCALE_STORAGE_KEY = 'proof-agent-locale'

interface LocaleContextValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  toggleLocale: () => void
  t: (key: string, fallback?: string) => string
  formatDateTime: (value: string | number | Date | null | undefined) => string
  formatNumber: (value: number) => string
}

const LocaleContext = createContext<LocaleContextValue | undefined>(undefined)

const TRANSLATIONS: Record<Locale, Record<string, string>> = {
  'en-US': {
    'language.switchToChinese': 'Switch language to Chinese',
    'language.switchToEnglish': 'Switch language to English',
    'language.chinese': '中文',
    'language.english': 'English',
    'topNav.toggleTheme': 'Toggle Theme',
    'nav.main': 'Main navigation',
    'nav.monitoring': 'Monitoring',
    'nav.configuration': 'Configuration',
    'nav.overview': 'Overview',
    'nav.runs': 'Runs',
    'nav.handoffs': 'Handoffs',
    'nav.approvals': 'Approvals',
    'nav.agents': 'Agents',
    'nav.policies': 'Policies',
    'nav.knowledge': 'Knowledge',
    'nav.models': 'Models',
    'nav.tools': 'Tools',
    'nav.settings': 'Settings',
    'common.runId': 'Run ID',
    'common.question': 'Question',
    'common.outcome': 'Outcome',
    'common.purpose': 'Purpose',
    'common.time': 'Time',
    'common.production': 'Production',
    'common.validation': 'Validation',
    'common.allRuns': 'All Runs',
    'outcome.answered': 'Answered',
    'outcome.refused': 'Refused',
    'outcome.escalated': 'Escalated',
    'outcome.clarify': 'Clarify',
    'outcome.waiting': 'Waiting',
    'outcome.denied': 'Denied',
    'outcome.failed': 'Failed',
    'overview.title': 'System Overview',
    'overview.description': 'Metrics and health for governed Agent execution.',
    'overview.totalRuns': 'Total Runs',
    'overview.totalRunsSubtitle': 'All time governed runs',
    'overview.answeredRate': 'Answered Rate',
    'overview.answeredRateSubtitle': 'Supported with citations',
    'overview.pendingApprovals': 'Pending Approvals',
    'overview.pendingApprovalsSubtitle': 'Awaiting human review',
    'overview.outcomeDistribution': 'Outcome Distribution',
    'overview.recentActivity': 'Recent Activity',
    'overview.viewAllRuns': 'View all runs →',
    'overview.noRuns': 'No runs yet. Run the demo to see data here.',
    'overview.justNow': 'just now',
    'overview.minutesAgo': '{count}m ago',
    'overview.hoursAgo': '{count}h ago',
    'overview.daysAgo': '{count}d ago',
    'runs.title': 'Runs Explorer',
    'runs.description': 'Search, filter, and inspect governed execution traces.',
    'runs.searchPlaceholder': 'Search by question or run ID...',
    'runs.allOutcomes': 'All Outcomes',
    'runs.answeredWithCitations': 'Answered with Citations',
    'runs.refusedNoEvidence': 'Refused - No Evidence',
    'runs.waitingForApproval': 'Waiting for Approval',
    'runs.toolApprovalDenied': 'Tool Approval Denied',
    'runs.failed': 'Failed',
    'runs.showing': 'Showing {shown} of {total} results',
    'runs.noMatches': 'No runs match your filters.',
    'agents.title': 'Agents',
    'agents.description': 'Configure drafts, validate changes, and publish governed versions.',
    'agents.create': '+ Create Agent',
    'agents.import': 'Import',
    'agents.importing': 'Importing',
    'agents.empty': 'No configured Agents yet.',
    'agents.drafts': 'Drafts',
    'agents.activeVersion': 'Active Version',
    'agents.updated': 'Updated',
    'agents.unpublished': 'unpublished',
    'approvals.title': 'Approval Queue',
    'approvals.description': 'Pending tool approvals ordered by expiration.',
    'approvals.count': '{shown} of {total}',
    'approvals.loadError': 'Unable to load approvals.',
    'approvals.empty': 'No pending approvals.',
    'approvals.status': 'Status',
    'approvals.run': 'Run',
    'approvals.tool': 'Tool',
    'approvals.parameters': 'Parameters',
    'approvals.expires': 'Expires',
    'approvals.expired': 'expired',
    'approvals.pending': 'pending',
    'approvals.unknownAgent': 'unknown agent',
    'approvals.parameter': 'parameter',
    'approvals.parametersCount': 'parameters',
    'approvals.none': 'none',
    'approvals.back': 'Back to Approvals',
    'handoffs.title': 'Handoff Monitor',
    'handoffs.description': 'Internal follow-up events from customer-facing runs.',
    'handoffs.loadError': 'Unable to load handoffs.',
    'handoffs.empty': 'No customer handoffs recorded.',
    'handoffs.reason': 'Reason',
    'handoffs.customer': 'Customer',
    'handoffs.summary': 'Summary',
    'handoffs.anonymous': 'anonymous',
    'policies.title': 'Policies',
    'policies.description': 'Browse governance policies across all agents. Edit within agent configuration.',
    'policies.loadError': 'Failed to load policies.',
    'policies.empty': 'No governance policies found across configured agents.',
    'policies.rule': 'rule',
    'policies.rules': 'rules',
    'policies.editInAgent': 'Edit in Agent',
    'tools.title': 'Tools',
    'tools.description': 'Browse tool contracts across all agents. Edit within agent configuration.',
    'tools.loadError': 'Unable to load tool contracts.',
    'tools.empty': 'No tool contracts found.',
    'tools.count': 'tools',
    'tools.editInAgent': 'Edit in Agent',
    'models.title': 'Models',
    'models.loadError': 'Unable to load model connections.',
    'models.createError': 'Unable to create model connection.',
    'models.created': 'Created {name}.',
    'models.displayName': 'Display Name',
    'models.connectionId': 'Connection ID',
    'models.provider': 'Provider',
    'models.modelIdentifier': 'Model Identifier',
    'models.baseUrl': 'Base URL',
    'models.credentialEnv': 'Credential Env',
    'models.timeoutSeconds': 'Timeout Seconds',
    'models.creating': 'Creating...',
    'models.create': 'Create Model',
    'models.search': 'Search',
    'models.providerFilter': 'Provider Filter',
    'models.allProviders': 'All providers',
    'models.lifecycle': 'Lifecycle',
    'models.allLifecycle': 'All lifecycle states',
    'models.activeOption': 'Active',
    'models.archivedOption': 'Archived',
    'models.active': 'active',
    'models.archived': 'archived',
    'models.references': 'References',
    'models.allReferences': 'All references',
    'models.referenced': 'Referenced',
    'models.unreferenced': 'Unreferenced',
    'models.smoke': 'Smoke',
    'models.allSmoke': 'All smoke states',
    'models.passed': 'Passed',
    'models.failed': 'Failed',
    'models.skipped': 'Skipped',
    'models.empty': 'No model connections match the current filters.',
    'models.refs': 'refs',
    'models.notTested': 'not tested',
    'knowledge.title': 'Knowledge Sources',
    'knowledge.description': 'Manage shared knowledge sources independently, then bind published snapshots from Agent configuration.',
    'knowledge.createTitle': 'Create Knowledge Source',
    'knowledge.createDescription': 'Configure a local index source for managed documents or connect a trusted HTTP JSON retrieval API.',
    'knowledge.loadError': 'Unable to load knowledge sources.',
    'knowledge.createError': 'Unable to create knowledge source.',
    'knowledge.created': 'Created {name}.',
    'knowledge.sourceType': 'Source Type',
    'knowledge.localIndex': 'Local Index',
    'knowledge.name': 'Name',
    'knowledge.sourceId': 'Source ID',
    'knowledge.ingestionModelSource': 'Ingestion Model Source',
    'knowledge.ingestionProvider': 'Ingestion Provider',
    'knowledge.ingestionModel': 'Ingestion Model',
    'knowledge.ingestionCredentialEnv': 'Ingestion Credential Env',
    'knowledge.routingModelSource': 'Routing Model Source',
    'knowledge.routingProvider': 'Routing Provider',
    'knowledge.routingModel': 'Routing Model',
    'knowledge.routingCredentialEnv': 'Routing Credential Env',
    'knowledge.documentSelectionBudget': 'Document Selection Budget',
    'knowledge.workerConcurrency': 'Worker Concurrency',
    'knowledge.remoteEndpoint': 'Remote Endpoint',
    'knowledge.headerValueEnv': 'Header Value Env',
    'knowledge.remoteTopK': 'Remote Top K',
    'knowledge.resultsPointer': 'Results Pointer',
    'knowledge.contentPointer': 'Content Pointer',
    'knowledge.scorePointer': 'Score Pointer',
    'knowledge.citationPointer': 'Citation Pointer',
    'knowledge.creating': 'Creating...',
    'knowledge.create': 'Create Source',
    'knowledge.empty': 'No knowledge sources configured.',
    'knowledge.ready': 'ready',
    'knowledge.published': 'published',
    'knowledge.draft': 'draft',
    'knowledge.custom': 'Custom',
  },
  'zh-CN': {
    'language.switchToChinese': '切换到中文',
    'language.switchToEnglish': '切换到 English',
    'language.chinese': '中文',
    'language.english': 'English',
    'topNav.toggleTheme': '切换主题',
    'nav.main': '主导航',
    'nav.monitoring': '监控',
    'nav.configuration': '配置',
    'nav.overview': '概览',
    'nav.runs': 'Runs',
    'nav.handoffs': '交接',
    'nav.approvals': '审批',
    'nav.agents': 'Agents',
    'nav.policies': 'Policies',
    'nav.knowledge': 'Knowledge',
    'nav.models': 'Models',
    'nav.tools': 'Tools',
    'nav.settings': '设置',
    'common.runId': 'Run ID',
    'common.question': '问题',
    'common.outcome': '结果',
    'common.purpose': '用途',
    'common.time': '时间',
    'common.production': 'Production',
    'common.validation': 'Validation',
    'common.allRuns': '全部 Runs',
    'outcome.answered': '已回答',
    'outcome.refused': '已拒绝',
    'outcome.escalated': '已升级',
    'outcome.clarify': '需澄清',
    'outcome.waiting': '等待中',
    'outcome.denied': '已拒批',
    'outcome.failed': '失败',
    'overview.title': '系统概览',
    'overview.description': '治理 Agent 执行的指标与健康状态。',
    'overview.totalRuns': 'Runs 总数',
    'overview.totalRunsSubtitle': '全部治理执行',
    'overview.answeredRate': '回答率',
    'overview.answeredRateSubtitle': '有 citations 支持',
    'overview.pendingApprovals': '待审批',
    'overview.pendingApprovalsSubtitle': '等待人工审核',
    'overview.outcomeDistribution': '结果分布',
    'overview.recentActivity': '近期活动',
    'overview.viewAllRuns': '查看全部 Runs →',
    'overview.noRuns': '暂无 Runs。运行 demo 后可在此查看数据。',
    'overview.justNow': '刚刚',
    'overview.minutesAgo': '{count} 分钟前',
    'overview.hoursAgo': '{count} 小时前',
    'overview.daysAgo': '{count} 天前',
    'runs.title': 'Runs Explorer',
    'runs.description': '检索、筛选并查看治理执行 Trace。',
    'runs.searchPlaceholder': '按问题或 Run ID 搜索...',
    'runs.allOutcomes': '全部结果',
    'runs.answeredWithCitations': '已回答，有 Citations',
    'runs.refusedNoEvidence': '拒绝 - 无 Evidence',
    'runs.waitingForApproval': '等待审批',
    'runs.toolApprovalDenied': 'Tool 审批被拒',
    'runs.failed': '失败',
    'runs.showing': '显示 {shown} / {total} 条结果',
    'runs.noMatches': '没有符合筛选条件的 Runs。',
    'agents.title': 'Agents',
    'agents.description': '配置 drafts、验证变更，并发布治理版本。',
    'agents.create': '+ 创建 Agent',
    'agents.import': '导入',
    'agents.importing': '导入中',
    'agents.empty': '暂无已配置的 Agents。',
    'agents.drafts': 'Drafts',
    'agents.activeVersion': 'Active Version',
    'agents.updated': '更新时间',
    'agents.unpublished': '未发布',
    'approvals.title': '审批队列',
    'approvals.description': '待处理的 tool 审批，按过期时间排序。',
    'approvals.count': '{shown} / {total}',
    'approvals.loadError': '无法加载审批。',
    'approvals.empty': '暂无待审批项。',
    'approvals.status': '状态',
    'approvals.run': 'Run',
    'approvals.tool': 'Tool',
    'approvals.parameters': '参数',
    'approvals.expires': '过期时间',
    'approvals.expired': '已过期',
    'approvals.pending': '待处理',
    'approvals.unknownAgent': '未知 Agent',
    'approvals.parameter': '个参数',
    'approvals.parametersCount': '个参数',
    'approvals.none': '无',
    'approvals.back': '返回审批队列',
    'handoffs.title': '交接监控',
    'handoffs.description': '来自 customer-facing runs 的内部跟进事件。',
    'handoffs.loadError': '无法加载交接记录。',
    'handoffs.empty': '暂无客户交接记录。',
    'handoffs.reason': '原因',
    'handoffs.customer': '客户',
    'handoffs.summary': '摘要',
    'handoffs.anonymous': '匿名',
    'policies.title': 'Policies',
    'policies.description': '浏览所有 Agents 的治理 policies。在 Agent 配置中编辑。',
    'policies.loadError': 'Policies 加载失败。',
    'policies.empty': '当前配置的 Agents 中没有治理 policies。',
    'policies.rule': '条 rule',
    'policies.rules': '条 rules',
    'policies.editInAgent': '在 Agent 中编辑',
    'tools.title': 'Tools',
    'tools.description': '浏览所有 Agents 的 tool contracts。在 Agent 配置中编辑。',
    'tools.loadError': '无法加载 tool contracts。',
    'tools.empty': '暂无 tool contracts。',
    'tools.count': '个 tools',
    'tools.editInAgent': '在 Agent 中编辑',
    'models.title': 'Models',
    'models.loadError': '无法加载 model connections。',
    'models.createError': '无法创建 model connection。',
    'models.created': '已创建 {name}。',
    'models.displayName': '显示名称',
    'models.connectionId': 'Connection ID',
    'models.provider': 'Provider',
    'models.modelIdentifier': 'Model Identifier',
    'models.baseUrl': 'Base URL',
    'models.credentialEnv': 'Credential Env',
    'models.timeoutSeconds': '超时秒数',
    'models.creating': '创建中...',
    'models.create': '创建 Model',
    'models.search': '搜索',
    'models.providerFilter': 'Provider 筛选',
    'models.allProviders': '全部 providers',
    'models.lifecycle': 'Lifecycle',
    'models.allLifecycle': '全部 lifecycle states',
    'models.activeOption': 'Active',
    'models.archivedOption': 'Archived',
    'models.active': 'active',
    'models.archived': 'archived',
    'models.references': 'References',
    'models.allReferences': '全部 references',
    'models.referenced': '已引用',
    'models.unreferenced': '未引用',
    'models.smoke': 'Smoke',
    'models.allSmoke': '全部 smoke states',
    'models.passed': '通过',
    'models.failed': '失败',
    'models.skipped': '跳过',
    'models.empty': '没有符合当前筛选条件的 model connections。',
    'models.refs': '个 refs',
    'models.notTested': '未测试',
    'knowledge.title': 'Knowledge Sources',
    'knowledge.description': '独立管理共享 knowledge sources，然后从 Agent 配置绑定已发布 snapshot。',
    'knowledge.createTitle': '创建 Knowledge Source',
    'knowledge.createDescription': '为受管文档配置 local index source，或连接可信 HTTP JSON retrieval API。',
    'knowledge.loadError': '无法加载 knowledge sources。',
    'knowledge.createError': '无法创建 knowledge source。',
    'knowledge.created': '已创建 {name}。',
    'knowledge.sourceType': 'Source Type',
    'knowledge.localIndex': 'Local Index',
    'knowledge.name': '名称',
    'knowledge.sourceId': 'Source ID',
    'knowledge.ingestionModelSource': 'Ingestion Model Source',
    'knowledge.ingestionProvider': 'Ingestion Provider',
    'knowledge.ingestionModel': 'Ingestion Model',
    'knowledge.ingestionCredentialEnv': 'Ingestion Credential Env',
    'knowledge.routingModelSource': 'Routing Model Source',
    'knowledge.routingProvider': 'Routing Provider',
    'knowledge.routingModel': 'Routing Model',
    'knowledge.routingCredentialEnv': 'Routing Credential Env',
    'knowledge.documentSelectionBudget': 'Document Selection Budget',
    'knowledge.workerConcurrency': 'Worker Concurrency',
    'knowledge.remoteEndpoint': 'Remote Endpoint',
    'knowledge.headerValueEnv': 'Header Value Env',
    'knowledge.remoteTopK': 'Remote Top K',
    'knowledge.resultsPointer': 'Results Pointer',
    'knowledge.contentPointer': 'Content Pointer',
    'knowledge.scorePointer': 'Score Pointer',
    'knowledge.citationPointer': 'Citation Pointer',
    'knowledge.creating': '创建中...',
    'knowledge.create': '创建 Source',
    'knowledge.empty': '暂无 knowledge sources。',
    'knowledge.ready': 'ready',
    'knowledge.published': 'published',
    'knowledge.draft': 'draft',
    'knowledge.custom': '自定义',
  },
}

const FALLBACK_LOCALE_CONTEXT: LocaleContextValue = {
  locale: 'en-US',
  setLocale: () => undefined,
  toggleLocale: () => undefined,
  t: (key, fallback) => TRANSLATIONS['en-US'][key] ?? fallback ?? key,
  formatDateTime: (input) => {
    if (input === null || input === undefined || input === '') return ''
    const date = input instanceof Date ? input : new Date(input)
    if (Number.isNaN(date.getTime())) return String(input)
    return new Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date)
  },
  formatNumber: (input) => new Intl.NumberFormat('en-US').format(input),
}

export function resolveLocaleFromLanguages(languages: readonly string[] | undefined): Locale {
  const preferred = languages?.find(Boolean)?.toLowerCase()
  return preferred?.startsWith('zh') ? 'zh-CN' : 'en-US'
}

function isLocale(value: string | null): value is Locale {
  return value === 'en-US' || value === 'zh-CN'
}

function browserLanguages(): string[] {
  if (typeof navigator === 'undefined') return []
  if (navigator.languages?.length) return [...navigator.languages]
  return navigator.language ? [navigator.language] : []
}

function initialLocale(): Locale {
  if (typeof localStorage !== 'undefined') {
    const stored = localStorage.getItem(LOCALE_STORAGE_KEY)
    if (isLocale(stored)) return stored
  }
  return resolveLocaleFromLanguages(browserLanguages())
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale)

  const setLocale = (nextLocale: Locale) => {
    setLocaleState(nextLocale)
  }

  useEffect(() => {
    document.documentElement.lang = locale
    localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  }, [locale])

  const value = useMemo<LocaleContextValue>(() => {
    const dictionary = TRANSLATIONS[locale]
    return {
      locale,
      setLocale,
      toggleLocale: () => setLocale(locale === 'en-US' ? 'zh-CN' : 'en-US'),
      t: (key, fallback) => dictionary[key] ?? fallback ?? key,
      formatDateTime: (input) => {
        if (input === null || input === undefined || input === '') return ''
        const date = input instanceof Date ? input : new Date(input)
        if (Number.isNaN(date.getTime())) return String(input)
        return new Intl.DateTimeFormat(locale, {
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(date)
      },
      formatNumber: (input) => new Intl.NumberFormat(locale).format(input),
    }
  }, [locale])

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale() {
  const context = useContext(LocaleContext)
  return context ?? FALLBACK_LOCALE_CONTEXT
}

export function LanguageToggleButton() {
  const { locale, toggleLocale, t } = useLocale()
  const isEnglish = locale === 'en-US'

  return (
    <button
      type="button"
      onClick={toggleLocale}
      className="rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
      aria-label={isEnglish ? t('language.switchToChinese') : t('language.switchToEnglish')}
    >
      {isEnglish ? t('language.chinese') : t('language.english')}
    </button>
  )
}
