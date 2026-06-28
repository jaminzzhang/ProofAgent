import { createContext, useContext, useEffect, useMemo, useState } from 'react'

export type Locale = 'en-US' | 'zh-CN'

/**
 * Shared locale engine for both the Dashboard and the Unified Chat.
 *
 * Each app registers its own translation dictionaries via `createLocaleApi`,
 * so the underlying context/provider/hook logic stays in sync (it was already
 * byte-identical between the two apps and silently drifting) while app-specific
 * keys live next to the app that uses them.
 */

const LOCALE_STORAGE_KEY = 'proof-agent-locale'

export interface LocaleContextValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  toggleLocale: () => void
  t: (key: string, fallback?: string) => string
  formatDateTime: (value: string | number | Date | null | undefined) => string
  formatNumber: (value: number) => string
}

const LocaleContext = createContext<LocaleContextValue | undefined>(undefined)

export function resolveLocaleFromLanguages(
  languages: readonly string[] | undefined,
): Locale {
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

/**
 * Shared core translations (theme toggle, language switch, outcome labels).
 * Apps merge their own dictionaries on top of these via `createLocaleApi`.
 */
const CORE_TRANSLATIONS: Record<Locale, Record<string, string>> = {
  'en-US': {
    'language.switchToChinese': 'Switch language to Chinese',
    'language.switchToEnglish': 'Switch language to English',
    'language.chinese': '中文',
    'language.english': 'English',
    'topNav.toggleTheme': 'Toggle Theme',
    'topNav.live': 'Live',
    'common.runId': 'Run ID',
    'common.question': 'Question',
    'common.outcome': 'Outcome',
    'common.copy': 'Copy',
    'common.copied': 'Copied',
    'outcome.answered': 'Answered',
    'outcome.refused': 'Refused',
    'outcome.escalated': 'Escalated',
    'outcome.clarify': 'Clarify',
    'outcome.waiting': 'Waiting',
    'outcome.denied': 'Denied',
    'outcome.policyDenied': 'Policy denied',
    'outcome.failed': 'Failed',
  },
  'zh-CN': {
    'language.switchToChinese': '切换到中文',
    'language.switchToEnglish': '切换到 English',
    'language.chinese': '中文',
    'language.english': 'English',
    'topNav.toggleTheme': '切换主题',
    'topNav.live': '在线',
    'common.runId': 'Run ID',
    'common.question': '问题',
    'common.outcome': '结果',
    'common.copy': '复制',
    'common.copied': '已复制',
    'outcome.answered': '已回答',
    'outcome.refused': '已拒绝',
    'outcome.escalated': '已升级',
    'outcome.clarify': '需澄清',
    'outcome.waiting': '等待中',
    'outcome.denied': '已拒批',
    'outcome.policyDenied': '策略拒绝',
    'outcome.failed': '失败',
  },
}

function mergeDictionaries(
  app: Partial<Record<Locale, Record<string, string>>>,
): Record<Locale, Record<string, string>> {
  return {
    'en-US': { ...CORE_TRANSLATIONS['en-US'], ...(app['en-US'] ?? {}) },
    'zh-CN': { ...CORE_TRANSLATIONS['zh-CN'], ...(app['zh-CN'] ?? {}) },
  }
}

/**
 * Build an app-specific LocaleProvider + useLocale + LanguageToggleButton bound
 * to the app's translation dictionaries. Keeps the public API identical to the
 * per-app files it replaces, so call sites need no changes beyond the import.
 */
export function createLocaleApi(appMessages: {
  en: Record<string, string>
  zh: Record<string, string>
}) {
  const TRANSLATIONS = mergeDictionaries({
    'en-US': appMessages.en,
    'zh-CN': appMessages.zh,
  })

  const FALLBACK_LOCALE_CONTEXT: LocaleContextValue = {
    locale: 'en-US',
    setLocale: () => undefined,
    toggleLocale: () => undefined,
    t: (key, fallback) =>
      TRANSLATIONS['en-US'][key] ?? fallback ?? key,
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

  function LocaleProvider({ children }: { children: React.ReactNode }) {
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

    return (
      <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
    )
  }

  function useLocale() {
    const context = useContext(LocaleContext)
    return context ?? FALLBACK_LOCALE_CONTEXT
  }

  function LanguageToggleButton() {
    const { locale, toggleLocale, t } = useLocale()
    const isEnglish = locale === 'en-US'

    return (
      <button
        type="button"
        onClick={toggleLocale}
        className="rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
        aria-label={
          isEnglish
            ? t('language.switchToChinese')
            : t('language.switchToEnglish')
        }
      >
        {isEnglish ? t('language.chinese') : t('language.english')}
      </button>
    )
  }

  return { LocaleProvider, useLocale, LanguageToggleButton, LocaleContext }
}
