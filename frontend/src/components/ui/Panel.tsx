import type { HTMLAttributes } from 'react'

import { cn } from '@/utils/cn'

interface PanelProps extends HTMLAttributes<HTMLDivElement> {
  tone?: 'default' | 'accent'
}

export function Panel({ className, tone = 'default', ...props }: PanelProps) {
  return (
    <div
      className={cn(
        'rounded-[30px] border border-neutral-300/90 bg-white/94 p-5 shadow-[0_22px_60px_rgba(15,23,42,0.08)] backdrop-blur-xl transition duration-300 md:p-6',
        tone === 'accent' && 'bg-neutral-50',
        className,
      )}
      {...props}
    />
  )
}
