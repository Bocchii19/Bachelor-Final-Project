import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

import { cn } from '@/utils/cn'

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  className?: string
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex h-full min-h-[220px] flex-col items-center justify-center gap-4 rounded-[28px] border border-dashed border-neutral-300 bg-gradient-to-b from-white to-neutral-50 px-6 py-10 text-center',
        className,
      )}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-black text-white shadow-[0_14px_28px_rgba(15,23,42,0.14)]">
        <Icon className="h-7 w-7" />
      </div>
      <div className="space-y-2">
        <h3 className="text-lg font-semibold text-neutral-950">{title}</h3>
        {description ? (
          <p className="max-w-md text-sm leading-6 text-neutral-600">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  )
}
