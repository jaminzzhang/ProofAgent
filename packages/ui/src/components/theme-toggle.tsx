import { Moon, Sun } from 'lucide-react'
import { useTheme } from './theme-provider'
import { cn } from '../lib/cn'

interface ThemeToggleButtonProps {
  className?: string
  /** Accessible label; app may pass a localized string. */
  label?: string
}

/**
 * Icon-only theme toggle. Uses lucide sun/moon glyphs (replaces the duplicated
 * inline SVGs in both apps) and tokens for all colors.
 */
export function ThemeToggleButton({ className, label = 'Toggle Theme' }: ThemeToggleButtonProps) {
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
        className,
      )}
    >
      {isDark ? <Sun size={17} strokeWidth={2} /> : <Moon size={17} strokeWidth={2} />}
    </button>
  )
}
