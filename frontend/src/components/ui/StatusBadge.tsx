import { cn } from '@/utils/cn'

interface StatusBadgeProps {
  label: string
  tone?: 'neutral' | 'info' | 'accent' | 'warning' | 'danger' | 'success'
  pulse?: boolean
  compact?: boolean
}

const toneMap: Record<NonNullable<StatusBadgeProps['tone']>, string> = {
  neutral: 'border-neutral-300 bg-white text-neutral-700',
  info: 'border-neutral-300 bg-neutral-100 text-neutral-700',
  accent: 'border-black bg-black text-white',
  warning: 'border-neutral-400 bg-neutral-200 text-neutral-900',
  danger: 'border-black bg-neutral-900 text-white',
  success: 'border-neutral-700 bg-neutral-800 text-white',
}

export function StatusBadge({
  label,
  tone = 'neutral',
  pulse = false,
  compact = false,
}: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]',
        compact && 'px-2.5 py-1 text-[10px]',
        toneMap[tone],
      )}
    >
      <span
        className={cn(
          'h-1.5 w-1.5 rounded-full bg-current opacity-80',
          pulse && 'animate-pulse-soft',
        )}
      />
      {label}
    </span>
  )
}
