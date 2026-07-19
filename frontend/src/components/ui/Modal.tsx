import type { ReactNode } from 'react'
import { X } from 'lucide-react'

import { cn } from '@/utils/cn'

interface ModalProps {
  open: boolean
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
  onClose: () => void
  widthClassName?: string
}

export function Modal({
  open,
  title,
  description,
  children,
  footer,
  onClose,
  widthClassName = 'max-w-2xl',
}: ModalProps) {
  if (!open) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/15 p-4 backdrop-blur-[2px]">
      <div
        className={cn(
          'w-full rounded-[30px] border border-neutral-300 bg-white shadow-[0_24px_80px_rgba(15,23,42,0.18)]',
          widthClassName,
        )}
      >
        <div className="flex items-start justify-between border-b border-neutral-200 px-6 py-5">
          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-neutral-950">{title}</h2>
            {description ? (
              <p className="max-w-xl text-sm leading-6 text-neutral-600">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-neutral-300 bg-white text-neutral-700 transition hover:bg-neutral-100 hover:text-black"
            aria-label="Close modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-5">{children}</div>
        {footer ? <div className="border-t border-neutral-200 px-6 py-5">{footer}</div> : null}
      </div>
    </div>
  )
}
