import type { ReactNode } from 'react'
import { BrandMark } from './brand-mark'
import { ThemeToggleButton } from './theme-toggle'
import { cn } from '../lib/cn'

interface TopNavProps {
  /** Slot before the brand mark (e.g. a back button in fullscreen shells). */
  leading?: ReactNode
  /** App title; defaults to the product name. */
  title?: ReactNode
  /** Optional subtitle under the title (e.g. agent display name). */
  subtitle?: ReactNode
  /** Slot next to the title for status pills, mode indicators, etc. */
  status?: ReactNode
  /** Center slot for global search, command palette, etc. */
  center?: ReactNode
  /** Right-aligned primary actions (env switcher, mode links). */
  actions?: ReactNode
  /** Show the theme toggle on the right. Defaults to true. */
  showThemeToggle?: boolean
  /** Show the language toggle on the right. Defaults to true. */
  showLanguageToggle?: boolean
  /** App-provided language toggle element (bound to the app's locale engine). */
  languageToggle?: ReactNode
  /** Right-most account/user menu element. */
  accountMenu?: ReactNode
  className?: string
}

/**
 * Unified top navigation bar for both the Dashboard and the Unified Chat.
 * Replaces the two diverging TopNav components (the dashboard's parameterized
 * version and chat's hardcoded one) with a single, slot-driven shell.
 */
export function TopNav({
  leading,
  title = 'Proof Agent',
  subtitle,
  status,
  center,
  actions,
  showThemeToggle = true,
  showLanguageToggle = true,
  languageToggle,
  accountMenu,
  className,
}: TopNavProps) {
  return (
    <header
      className={cn(
        'sticky top-0 z-50 flex h-14 items-center justify-between gap-4 border-b border-[var(--border)] bg-[var(--bg-surface)]/90 px-4 backdrop-blur-md md:px-6',
        className,
      )}
    >
      {/* Left: brand + title */}
      <div className="flex min-w-0 items-center gap-2.5">
        {leading}
        <BrandMark size="md" />
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <div className="min-w-0">
            <div className="truncate font-semibold tracking-tight text-[var(--text-primary)]">
              {title}
            </div>
            {subtitle && (
              <div className="mt-0.5 hidden max-w-xl truncate text-xs text-[var(--text-muted)] md:block">
                {subtitle}
              </div>
            )}
          </div>
          {status}
        </div>
      </div>

      {/* Center: search / command palette */}
      {center && <div className="hidden min-w-0 max-w-md flex-1 md:block">{center}</div>}

      {/* Right: actions + toggles + account */}
      <div className="flex items-center gap-2">
        {actions}
        {showLanguageToggle && languageToggle}
        {showThemeToggle && <ThemeToggleButton />}
        {accountMenu}
      </div>
    </header>
  )
}
