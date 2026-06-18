import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge Tailwind class names safely: clsx for conditional arrays,
 * tailwind-merge to de-duplicate conflicting utilities (e.g. `px-2 px-4`).
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
