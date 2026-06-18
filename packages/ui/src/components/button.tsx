import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { forwardRef } from 'react'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../lib/cn'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-surface)] disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default:
          'bg-[var(--accent)] text-[var(--accent-fg)] hover:bg-[var(--accent-hover)]',
        outline:
          'border border-[var(--border-strong)] bg-[var(--bg-surface)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]',
        ghost:
          'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
        subtle:
          'bg-[var(--bg-hover)] text-[var(--text-primary)] hover:bg-[var(--bg-active)]',
        destructive:
          'bg-[var(--danger)] text-white hover:opacity-90',
        'destructive-outline':
          'border border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger-fg)] hover:bg-[var(--danger-bg)]',
        link:
          'text-[var(--success-fg)] underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 px-3 text-xs',
        md: 'h-9 px-4',
        lg: 'h-10 px-5 text-[15px]',
        icon: 'h-8 w-8',
        'icon-sm': 'h-7 w-7',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

/**
 * Primary button primitive with semantic variants. Replaces the dozens of
 * duplicated inline button class strings across both apps.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  },
)
Button.displayName = 'Button'

export { buttonVariants }
