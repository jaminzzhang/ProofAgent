// @proofagent/ui — shared design system for Proof Agent Dashboard + Chat

// Utilities
export { cn } from './lib/cn'

// Theme + i18n engine
export { ThemeProvider, useTheme } from './components/theme-provider'
export { ThemeToggleButton } from './components/theme-toggle'
export {
  createLocaleApi,
  resolveLocaleFromLanguages,
  type Locale,
  type LocaleContextValue,
} from './i18n/locale'

// Brand + layout
export { BrandMark } from './components/brand-mark'
export { TopNav } from './components/top-nav'

// Primitives — form controls
export { Button, buttonVariants, type ButtonProps } from './components/button'
export { Input, type InputProps } from './components/input'
export { Textarea, type TextareaProps } from './components/textarea'
export { Label } from './components/label'
export { Switch } from './components/switch'
export { Checkbox } from './components/checkbox'

// Primitives — display
export {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from './components/card'
export { Badge, badgeVariants, type BadgeProps } from './components/badge'
export { Separator } from './components/separator'
export { Skeleton } from './components/skeleton'
export {
  Avatar,
  AvatarImage,
  AvatarFallback,
} from './components/avatar'

// Primitives — overlay / interactive
export {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from './components/tabs'
export {
  Dialog,
  DialogTrigger,
  DialogPortal,
  DialogClose,
  DialogOverlay,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from './components/dialog'
export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  SelectScrollUpButton,
  SelectScrollDownButton,
} from './components/select'
export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuGroup,
  DropdownMenuPortal,
  DropdownMenuSub,
  DropdownMenuRadioGroup,
} from './components/dropdown-menu'
export {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from './components/tooltip'

// Primitives — data
export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
} from './components/table'

// Content
export { Markdown } from './components/markdown'

// Configuration layout substrate (Agent Detail config tabs)
export { ConfigPanel, type ConfigPanelProps, type ConfigPanelVariant } from './components/config-panel'
export { SectionField, type SectionFieldProps } from './components/section-field'
export { FieldGrid, type FieldGridProps } from './components/field-grid'
export {
  KeyValueList,
  type KeyValueListProps,
  type KeyValueItem,
  type KeyValueValueKind,
} from './components/key-value-list'
export { ReferenceChips, type ReferenceChipsProps } from './components/reference-chips'

// Domain-aligned shared components
export {
  OutcomeBadge,
  OUTCOME_STYLES,
  outcomeCategory,
  type ReceiptOutcome,
} from './components/outcome-badge'
export { StatusDot } from './components/status-dot'
export { EmptyState } from './components/empty-state'
export { CodeBlock } from './components/code-block'
export { LoadingSpinner } from './components/loading-spinner'
export { CopyButton } from './components/copy-button'

// Feedback
export { ToasterProvider, useToast } from './components/toaster'
