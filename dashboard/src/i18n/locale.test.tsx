// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  LanguageToggleButton,
  LocaleProvider,
  resolveLocaleFromLanguages,
  useLocale,
} from './locale'

function LocaleProbe() {
  const { locale, formatDateTime } = useLocale()
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span data-testid="date">{formatDateTime('2026-06-18T08:30:00Z')}</span>
      <LanguageToggleButton />
    </div>
  )
}

function installLocalStorageMock() {
  const values = new Map<string, string>()
  const storage: Storage = {
    get length() {
      return values.size
    },
    clear: vi.fn(() => values.clear()),
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    key: vi.fn((index: number) => [...values.keys()][index] ?? null),
    removeItem: vi.fn((key: string) => values.delete(key)),
    setItem: vi.fn((key: string, value: string) => values.set(key, value)),
  }

  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: storage,
  })
}

describe('locale support', () => {
  beforeEach(() => {
    installLocalStorageMock()
  })

  afterEach(() => {
    cleanup()
    localStorage.clear()
    document.documentElement.lang = ''
  })

  it('defaults Simplified Chinese for zh browser languages', () => {
    expect(resolveLocaleFromLanguages(['zh-Hans-CN', 'en-US'])).toBe('zh-CN')
  })

  it('defaults English for non-Chinese browser languages', () => {
    expect(resolveLocaleFromLanguages(['fr-FR', 'en-US'])).toBe('en-US')
  })

  it('uses a persisted manual locale preference across sessions', () => {
    localStorage.setItem('proof-agent-locale', 'zh-CN')

    render(
      <LocaleProvider>
        <LocaleProbe />
      </LocaleProvider>,
    )

    expect(screen.getByTestId('locale')).toHaveTextContent('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(screen.getByTestId('date')).toHaveTextContent('2026')
  })

  it('toggles locale and persists the selected language', () => {
    localStorage.setItem('proof-agent-locale', 'en-US')

    render(
      <LocaleProvider>
        <LocaleProbe />
      </LocaleProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Switch language to Chinese' }))

    expect(screen.getByTestId('locale')).toHaveTextContent('zh-CN')
    expect(localStorage.getItem('proof-agent-locale')).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(screen.getByRole('button', { name: '切换到 English' })).toBeInTheDocument()
  })
})
