import { Clock3 } from 'lucide-react'
import { useState } from 'react'

import { StatusBadge } from '@/components/ui/StatusBadge'
import { AI_CORE_ICONS } from '@/features/ai-cores/coreIcons'
import { AI_CORE_MAP } from '@/mocks/aiCores'
import { apiConfig } from '@/services/config'
import type { EventItem } from '@/types/event'
import { cn } from '@/utils/cn'
import { formatRelativeTime, formatTimeOnly, formatTimestamp } from '@/utils/format'

interface EventCardProps {
  event: EventItem
}

function severityTone(severity: EventItem['severity']) {
  if (severity === 'high') {
    return 'danger'
  }

  if (severity === 'medium') {
    return 'warning'
  }

  return 'info'
}

function resolveImageUrl(url: string | null | undefined): string | null {
  if (!url) return null
  if (url.startsWith('http')) return url
  // Relative URL → prepend backend base (remove /api suffix)
  const backendRoot = apiConfig.baseUrl.replace(/\/api\/?$/, '')
  return `${backendRoot}${url}`
}

export function EventCard({ event }: EventCardProps) {
  const Icon = AI_CORE_ICONS[event.core]
  const imgSrc = resolveImageUrl(event.imageUrl)
  const [expanded, setExpanded] = useState(false)

  return (
    <article
      className={cn(
        'rounded-[22px] border bg-white p-4 shadow-sm transition hover:shadow-md',
        event.isNew ? 'border-black' : 'border-neutral-200',
      )}
    >
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-black text-white">
          <Icon className="h-4.5 w-4.5" />
        </div>

        <div className="min-w-0 flex-1 space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-neutral-950">{event.cameraName}</p>
            <StatusBadge label={AI_CORE_MAP[event.core].shortLabel} tone="info" compact />
            <StatusBadge label={event.severity} tone={severityTone(event.severity)} compact />
            {event.isNew ? <StatusBadge label="New" tone="accent" pulse compact /> : null}
          </div>

          <p className="text-sm leading-6 text-neutral-700">{event.message}</p>

          {/* Event capture image */}
          {imgSrc && (
            <div className="mt-1">
              <img
                src={imgSrc}
                alt={`Capture ${event.cameraName}`}
                onClick={() => setExpanded(!expanded)}
                className={cn(
                  'cursor-pointer rounded-lg border border-neutral-200 object-cover shadow-sm transition-all hover:shadow-md',
                  expanded ? 'max-h-[400px] w-full' : 'h-20 w-32',
                )}
                loading="lazy"
              />
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3 text-xs text-neutral-500">
            <span className="inline-flex items-center gap-1.5">
              <Clock3 className="h-3.5 w-3.5" />
              {formatTimeOnly(event.createdAt)}
            </span>
            <span>{formatRelativeTime(event.createdAt)}</span>
            <span className="font-mono">{formatTimestamp(event.createdAt)}</span>
          </div>
        </div>
      </div>
    </article>
  )
}
