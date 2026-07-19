import { BellRing, Filter, Trash2 } from 'lucide-react'

import { EmptyState } from '@/components/ui/EmptyState'
import { Panel } from '@/components/ui/Panel'
import { EventCard } from '@/features/events/EventCard'
import { AI_CORE_DEFINITIONS } from '@/mocks/aiCores'
import type { EventFilters, EventItem } from '@/types/event'

interface EventPanelProps {
  events: EventItem[]
  filters: EventFilters
  onChangeFilters: (filters: Partial<EventFilters>) => void
  onClearEvents: () => void
}

export function EventPanel({
  events,
  filters,
  onChangeFilters,
  onClearEvents,
}: EventPanelProps) {
  return (
    <Panel className="flex h-full min-h-[720px] flex-col lg:min-h-[640px]">
      <div className="flex flex-col gap-4 border-b border-neutral-200 pb-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[22px] font-semibold tracking-[0.14em] text-black">
              SỰ KIỆN
            </p>
          </div>
          <div className="rounded-2xl border border-neutral-300 bg-neutral-50 px-4 py-2 text-center">
            <div className="text-lg font-semibold text-neutral-950">{events.length}</div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-neutral-500">Visible</div>
          </div>
        </div>

        <div className="grid gap-3">
          <label className="space-y-2 text-xs font-semibold tracking-[0.06em] text-neutral-600">
            <span className="inline-flex items-center gap-2">
              <Filter className="h-3.5 w-3.5" />
              Lọc tính năng
            </span>
            <select
              value={filters.core}
              onChange={(event) =>
                onChangeFilters({ core: event.target.value as EventFilters['core'] })
              }
              className="h-11 w-full rounded-2xl border border-neutral-300 bg-neutral-50 px-4 text-sm text-neutral-900 outline-none transition focus:border-neutral-500 focus:bg-white"
            >
              <option value="all">Tất cả</option>
              {AI_CORE_DEFINITIONS.map((core) => (
                <option key={core.key} value={core.key}>
                  {core.shortLabel}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          type="button"
          onClick={onClearEvents}
          className="inline-flex items-center justify-center gap-2 rounded-2xl border border-neutral-300 bg-white px-4 py-3 text-sm font-semibold text-neutral-900 transition hover:bg-neutral-100"
        >
          <Trash2 className="h-4 w-4" />
          Xóa lịch sử sự kiện
        </button>
      </div>

      <div className="mt-5 flex-1 overflow-y-auto rounded-[26px] border border-neutral-200 bg-neutral-50/80 p-2">
        {events.length > 0 ? (
          <div className="space-y-3">
            {events.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </div>
        ) : (
          <EmptyState icon={BellRing} title="Không có sự kiện" className="min-h-[360px]" />
        )}
      </div>
    </Panel>
  )
}
