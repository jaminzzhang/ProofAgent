/**
 * Unified Chat locale entry point.
 *
 * Thin shim over the shared @proofagent/ui locale engine. The engine owns the
 * provider/hook/format logic and core keys; chat-specific keys live in
 * `./messages`. Exports keep the same shape as the original local file so all
 * existing imports (`LocaleProvider`, `useLocale`, `LanguageToggleButton`,
 * `Locale`, `resolveLocaleFromLanguages`) continue to work unchanged.
 */
import { createLocaleApi, resolveLocaleFromLanguages } from '@proofagent/ui'
import type { Locale, LocaleContextValue } from '@proofagent/ui'
import { chatMessages } from './messages'

const api = createLocaleApi({
  en: chatMessages['en-US'],
  zh: chatMessages['zh-CN'],
})

export const LocaleProvider = api.LocaleProvider
export const useLocale = api.useLocale
export const LanguageToggleButton = api.LanguageToggleButton
export { resolveLocaleFromLanguages }
export type { Locale, LocaleContextValue }
