import { Plus } from 'lucide-react'

import { StatusBadge } from '@/components/ui/StatusBadge'
import type { Camera } from '@/types/camera'
import { cn } from '@/utils/cn'

interface CameraTabsProps {
  cameras: Camera[]
  selectedCameraId: string | null
  eventCounts: Record<string, number>
  onSelectCamera: (cameraId: string) => void
  onAddCamera: () => void
}

function getStatusTone(camera: Camera) {
  if (camera.isViewing) {
    return 'accent'
  }

  if (camera.aiRunning) {
    return 'warning'
  }

  return 'info'
}

export function CameraTabs({
  cameras,
  selectedCameraId,
  eventCounts,
  onSelectCamera,
  onAddCamera,
}: CameraTabsProps) {
  return (
    <div className="flex flex-col">
      {/* Tab strip */}
      <div className="flex items-end gap-0 overflow-x-auto pl-2">
        {cameras.map((camera) => {
          const isSelected = selectedCameraId === camera.id
          const count = eventCounts[camera.id] ?? 0

          return (
            <button
              key={camera.id}
              type="button"
              onClick={() => onSelectCamera(camera.id)}
              className={cn(
                'group relative flex min-w-[280px] max-w-[360px] items-center gap-3 border-x border-t px-4 transition-all duration-200',
                isSelected
                  ? 'z-10 rounded-t-xl border-neutral-300 bg-white pb-3 pt-3 shadow-[0_-2px_8px_rgba(0,0,0,0.04)]'
                  : 'rounded-t-lg border-transparent bg-neutral-200/60 pb-2.5 pt-2.5 hover:bg-neutral-200',
                !isSelected && 'mt-1',
              )}
            >
              {/* Active indicator line at top */}
              {isSelected && (
                <span className="absolute inset-x-0 top-0 h-[2.5px] rounded-full bg-neutral-900" />
              )}

              {/* Camera info */}
              <div className="min-w-0 flex-1 text-left">
                <p
                  className={cn(
                    'truncate text-[26px] font-semibold leading-tight',
                    isSelected ? 'text-neutral-900' : 'text-neutral-600',
                  )}
                >
                  {camera.name}
                </p>
                <p
                  className={cn(
                    'mt-0.5 truncate text-[20px] tracking-[0.06em]',
                    isSelected ? 'text-neutral-500' : 'text-neutral-400',
                  )}
                >
                  {camera.location}
                </p>
              </div>

              {/* Event count badge */}
              {count > 0 && (
                <span
                  className={cn(
                    'flex h-6 min-w-[24px] items-center justify-center rounded-full px-1.5 text-[11px] font-bold',
                    isSelected
                      ? 'bg-neutral-900 text-white'
                      : 'bg-neutral-400/30 text-neutral-600',
                  )}
                >
                  {count}
                </span>
              )}

              {/* Separator between tabs */}
              {!isSelected && (
                <span className="absolute right-0 top-[20%] h-[60%] w-px bg-neutral-300/80" />
              )}
            </button>
          )
        })}

        {/* Add tab button */}
        <button
          type="button"
          onClick={onAddCamera}
          className="mt-1 flex items-center gap-1.5 rounded-t-lg border-x border-t border-transparent bg-transparent px-3 pb-2.5 pt-2.5 text-neutral-500 transition-colors hover:bg-neutral-200/60 hover:text-neutral-700"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>

      {/* Connected content bar (the "body" the active tab opens into) */}
      <div className="rounded-b-2xl rounded-tr-2xl border border-neutral-300 bg-white px-5 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.05)]">
        {cameras.length === 0 ? (
          <p className="py-2 text-sm text-neutral-400">
            No cameras configured. Click + to add one.
          </p>
        ) : (
          (() => {
            const camera = cameras.find((c) => c.id === selectedCameraId)
            if (!camera) {
              return (
                <p className="py-2 text-sm text-neutral-400">
                  Select a camera tab above.
                </p>
              )
            }

            return (
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <StatusBadge
                    label={
                      camera.status === 'ready'
                        ? 'Ready'
                        : camera.status === 'viewing'
                          ? 'Viewing'
                          : 'AI Running'
                    }
                    tone={getStatusTone(camera)}
                    pulse={camera.isViewing}
                    compact
                  />
                  <StatusBadge
                    label={camera.health}
                    tone={
                      camera.health === 'online'
                        ? 'success'
                        : camera.health === 'unstable'
                          ? 'warning'
                          : 'danger'
                    }
                    compact
                  />
                </div>
              </div>
            )
          })()
        )}
      </div>
    </div>
  )
}
