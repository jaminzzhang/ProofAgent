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
    'topNav.live': 'Live',
    'topNav.toggleTheme': 'Toggle Theme',
    'modeSelection.status': 'API Live',
    'modeSelection.description': 'Choose the chat surface for this session.',
    'modeSelection.operatorDescription': 'Internal governed QA with audit and approval context.',
    'modeSelection.customerDescription': 'Customer-safe service chat for policy and claim support.',
    'agentSelection.unavailable': '{agentId} is unavailable',
    'chatShell.noOutput': 'No output generated.',
    'chatShell.working': 'Working...',
    'chatShell.networkSupplement': 'Network supplement',
    'history.newChat': 'New Chat',
    'history.noConversations': 'No conversations yet.',
    'history.startHint': 'Click "New Chat" to start.',
    'history.newConversation': 'New Conversation',
    'history.rename': 'Rename',
    'history.pin': 'Pin to Top',
    'history.unpin': 'Unpin',
    'history.delete': 'Delete',
    'history.cancel': 'Cancel',
    'history.deleteConfirm': 'Delete this conversation? This cannot be undone.',
    'history.conversationMenu': 'Conversation actions',
    'operator.title': 'Operator Chat',
    'operator.emptyDescription': 'Select a conversation from the sidebar or start a new one.',
    'operator.loadErrorTitle': 'Unable to Load Conversation',
    'operator.loadConversationError': 'Failed to load conversation. It may have been deleted or the server is unavailable.',
    'operator.retry': 'Retry',
    'operator.loadAgentsError': 'Failed to load Published Agents.',
    'operator.sendError': 'Failed to send message. Please try again.',
    'operator.chooseAgentTitle': 'Choose a Published Agent',
    'operator.chooseAgentDescription': 'Select a Published Agent before starting operator chat.',
    'operator.unableLoadAgents': 'Unable to load Published Agents',
    'operator.noAgentsTitle': 'No Published Agents are available',
    'operator.unpublishedAgent': 'This Agent is not published for operator chat. Publish it before opening chat.',
    'operator.noAgentsDescription': 'Import an Agent template, validate it, and publish it in the Dashboard first.',
    'operator.defaultSubtitle': 'Operator-facing governed question answering.',
    'operator.placeholder': 'Type your question for the assistant',
    'operator.submit': 'Ask',
    'operator.emptyTitle': 'Start a Conversation',
    'operator.chatEmptyDescription': 'Ask the Insurance Service QA agent anything about policies or processes.',
    'operator.showGovernanceDetails': 'Show governance details',
    'operator.executing': 'Harness executing...',
    'operator.evidence': 'Evidence',
    'operator.source': 'Source',
    'operator.sources': 'Sources',
    'operator.auditTrace': 'Audit Trace',
    'operator.receipt': 'Receipt',
    'operator.reviewApproval': 'Review Approval Request',
    'operator.governanceSummary': 'ReAct Governance',
    'customer.title': 'Customer Chat',
    'customer.loadConversationError': 'The conversation is unavailable. Please start a new session.',
    'customer.loadAgentsError': 'Failed to load Customer-Facing Published Agents.',
    'customer.sendError': 'The service is unavailable. Please try again.',
    'customer.noAgentError': 'No Customer-Facing Published Agent selected.',
    'customer.chooseAgentTitle': 'Choose a Customer-Facing Published Agent',
    'customer.chooseAgentDescription': 'Select a Customer-Facing Published Agent before starting customer chat.',
    'customer.choosePublishedAgentDescription': 'Select a Published Agent before starting customer chat.',
    'customer.unableLoadAgents': 'Unable to load Customer-Facing Published Agents',
    'customer.noAgentsTitle': 'No Customer-Facing Published Agents are available',
    'customer.unpublishedAgent': 'This Agent is not published for customer chat. Publish a customer-facing Agent before opening chat.',
    'customer.noAgentsDescription': 'Import an Agent template, validate it, and publish a customer-facing Agent in the Dashboard first.',
    'customer.defaultSubtitle': 'Customer-safe service chat for policy and claim support.',
    'customer.placeholder': 'Ask about a policy, claim, or reimbursement',
    'customer.submit': 'Send',
    'customer.emptyTitle': 'Start a Conversation',
    'customer.emptyDescription': 'Ask a customer-safe service question.',
    'customer.starter.inpatientClaim': 'What documents are required for inpatient claim reimbursement?',
    'customer.starter.policyStatus': 'What is my policy status?',
    'customer.starter.claimStatus': 'What is the status of claim CLM-001?',
    'customer.sidebar.session': 'Session',
    'customer.sidebar.customer': 'Customer',
    'customer.sidebar.anonymous': 'Anonymous',
    'customer.sidebar.turns': 'Turns',
    'customer.sidebar.recentSources': 'Recent Sources',
    'customer.sidebar.noSources': 'No sources yet',
    'customer.mode.guest': 'Guest',
    'customer.feedback.helpful': 'Helpful',
    'customer.feedback.notHelpful': 'Not helpful',
    'customer.feedback.received': 'Feedback received',
    'progress.authenticating': 'Authenticating',
    'progress.retrievingEvidence': 'Retrieving evidence',
    'progress.checkingAccountData': 'Checking account data',
    'progress.validatingAnswer': 'Validating answer',
    'progress.preparingResponse': 'Preparing response',
    'progress.completed': 'Completed',
  },
  'zh-CN': {
    'language.switchToChinese': '切换到中文',
    'language.switchToEnglish': '切换到 English',
    'language.chinese': '中文',
    'language.english': 'English',
    'topNav.live': '在线',
    'topNav.toggleTheme': '切换主题',
    'modeSelection.status': 'API 在线',
    'modeSelection.description': '选择本次会话的 Chat 界面。',
    'modeSelection.operatorDescription': '内部治理问答，包含审计和审批上下文。',
    'modeSelection.customerDescription': '面向客户的安全服务 Chat，用于保单和理赔支持。',
    'agentSelection.unavailable': '{agentId} 不可用',
    'chatShell.noOutput': '未生成输出。',
    'chatShell.working': '处理中...',
    'chatShell.networkSupplement': '网络补充',
    'history.newChat': '新建 Chat',
    'history.noConversations': '暂无会话。',
    'history.startHint': '点击“新建 Chat”开始。',
    'history.newConversation': '新会话',
    'history.rename': '重命名',
    'history.pin': '置顶',
    'history.unpin': '取消置顶',
    'history.delete': '删除',
    'history.cancel': '取消',
    'history.deleteConfirm': '删除这个会话？此操作无法撤销。',
    'history.conversationMenu': '会话操作',
    'operator.title': 'Operator Chat',
    'operator.emptyDescription': '从侧栏选择一个会话，或新建一个会话。',
    'operator.loadErrorTitle': '无法加载会话',
    'operator.loadConversationError': '会话加载失败。它可能已被删除，或服务器不可用。',
    'operator.retry': '重试',
    'operator.loadAgentsError': 'Published Agents 加载失败。',
    'operator.sendError': '消息发送失败。请重试。',
    'operator.chooseAgentTitle': '选择 Published Agent',
    'operator.chooseAgentDescription': '开始 operator chat 前，请先选择一个 Published Agent。',
    'operator.unableLoadAgents': '无法加载 Published Agents',
    'operator.noAgentsTitle': '暂无可用的 Published Agents',
    'operator.unpublishedAgent': '这个 Agent 尚未发布到 operator chat。请先发布再打开 Chat。',
    'operator.noAgentsDescription': '请先在 Dashboard 导入 Agent template，完成验证并发布。',
    'operator.defaultSubtitle': '面向操作员的治理问答。',
    'operator.placeholder': '输入给 assistant 的问题',
    'operator.submit': '提问',
    'operator.emptyTitle': '开始会话',
    'operator.chatEmptyDescription': '向 Insurance Service QA agent 询问保单或流程问题。',
    'operator.showGovernanceDetails': '显示治理详情',
    'operator.executing': 'Harness 执行中...',
    'operator.evidence': 'Evidence',
    'operator.source': 'Source',
    'operator.sources': 'Sources',
    'operator.auditTrace': 'Audit Trace',
    'operator.receipt': 'Receipt',
    'operator.reviewApproval': '查看审批请求',
    'operator.governanceSummary': 'ReAct Governance',
    'customer.title': 'Customer Chat',
    'customer.loadConversationError': '会话不可用。请开始一个新会话。',
    'customer.loadAgentsError': 'Customer-Facing Published Agents 加载失败。',
    'customer.sendError': '服务暂不可用。请重试。',
    'customer.noAgentError': '未选择 Customer-Facing Published Agent。',
    'customer.chooseAgentTitle': '选择 Customer-Facing Published Agent',
    'customer.chooseAgentDescription': '开始 customer chat 前，请先选择一个 Customer-Facing Published Agent。',
    'customer.choosePublishedAgentDescription': '开始 customer chat 前，请先选择一个 Published Agent。',
    'customer.unableLoadAgents': '无法加载 Customer-Facing Published Agents',
    'customer.noAgentsTitle': '暂无可用的 Customer-Facing Published Agents',
    'customer.unpublishedAgent': '这个 Agent 尚未发布到 customer chat。请先发布面向客户的 Agent 再打开 Chat。',
    'customer.noAgentsDescription': '请先在 Dashboard 导入 Agent template，完成验证并发布面向客户的 Agent。',
    'customer.defaultSubtitle': '面向客户的安全服务 Chat，用于保单和理赔支持。',
    'customer.placeholder': '询问保单、理赔或报销问题',
    'customer.submit': '发送',
    'customer.emptyTitle': '开始会话',
    'customer.emptyDescription': '询问一个面向客户的安全服务问题。',
    'customer.starter.inpatientClaim': '住院理赔报销需要哪些材料？',
    'customer.starter.policyStatus': '我的保单状态是什么？',
    'customer.starter.claimStatus': '理赔 CLM-001 的状态是什么？',
    'customer.sidebar.session': '会话',
    'customer.sidebar.customer': '客户',
    'customer.sidebar.anonymous': '匿名',
    'customer.sidebar.turns': '轮次',
    'customer.sidebar.recentSources': '最近来源',
    'customer.sidebar.noSources': '暂无来源',
    'customer.mode.guest': '访客',
    'customer.feedback.helpful': '有帮助',
    'customer.feedback.notHelpful': '没有帮助',
    'customer.feedback.received': '反馈已收到',
    'progress.authenticating': '正在认证',
    'progress.retrievingEvidence': '正在检索 evidence',
    'progress.checkingAccountData': '正在检查账户数据',
    'progress.validatingAnswer': '正在验证回答',
    'progress.preparingResponse': '正在准备回复',
    'progress.completed': '已完成',
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
