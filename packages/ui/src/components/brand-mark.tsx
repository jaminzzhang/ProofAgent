import { ShieldCheck } from 'lucide-react'
import { cn } from '../lib/cn'

interface BrandMarkProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZE_STYLES: Record<NonNullable<BrandMarkProps['size']>, { box: string; icon: number }> = {
  sm: { box: 'w-6 h-6 rounded-[5px]', icon: 14 },
  md: { box: 'w-7 h-7 rounded-[6px]', icon: 16 },
  lg: { box: 'w-9 h-9 rounded-[8px]', icon: 20 },
}

/**
 * Proof Agent brand mark: a shield-check glyph in an accent-filled rounded tile.
 * Replaces the duplicated inline shield SVGs in both apps' TopNav components.
 */
export function BrandMark({ size = 'md', className }: BrandMarkProps) {
  const styles = SIZE_STYLES[size]
  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center bg-[var(--accent)] text-[var(--accent-fg)]',
        styles.box,
        className,
      )}
      aria-hidden="true"
    >
      <ShieldCheck size={styles.icon} strokeWidth={2.25} />
    </div>
  )
}
