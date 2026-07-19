import { useEffect, useState } from 'react'
import { Camera, Layers, MonitorPlay, Scan, WifiOff } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState } from '@/components/ui/EmptyState'
import { Panel } from '@/components/ui/Panel'
import { StatusBadge } from '@/components/ui/StatusBadge'
import * as cameraService from '@/services/cameraService'
import type { OverlayState } from '@/services/cameraService'
import type { Camera as CameraItem, StreamSession } from '@/types/camera'

interface LiveStreamPanelProps {
  camera: CameraItem | null
  activeStream: StreamSession | null
}

export function LiveStreamPanel({ camera, activeStream }: LiveStreamPanelProps) {
  const isViewing = Boolean(camera && activeStream && activeStream.cameraId === camera.id)

  // ── Overlay toggle state ──
  const [overlayState, setOverlayState] = useState<OverlayState>({
    show_region: false,
    show_bbox: false,
  })

  // Fetch overlay status when camera changes
  useEffect(() => {
    if (!camera) return
    void cameraService.getOverlayStatus(camera.id).then(setOverlayState)
  }, [camera?.id])

  const handleToggleRegion = () => {
    if (!camera) return
    const next = !overlayState.show_region
    setOverlayState((prev) => ({ ...prev, show_region: next }))
    void cameraService.toggleOverlay(camera.id, next, undefined).then((state) => {
      setOverlayState(state)
      toast.success(next ? 'Region overlay: ON' : 'Region overlay: OFF')
    })
  }

  const handleToggleBbox = () => {
    if (!camera) return
    const next = !overlayState.show_bbox
    setOverlayState((prev) => ({ ...prev, show_bbox: next }))
    void cameraService.toggleOverlay(camera.id, undefined, next).then((state) => {
      setOverlayState(state)
      toast.success(next ? 'BBox overlay: ON' : 'BBox overlay: OFF')
    })
  }

  return (
    <Panel className="flex flex-col">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-neutral-200 pb-5">
        <div>
          <p className="text-[22px] font-semibold uppercase tracking-[0.22em] text-black">
            XEM TRỰC TUYẾN
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge
            label={isViewing ? 'Viewing' : 'Standby'}
            tone={isViewing ? 'accent' : 'neutral'}
            pulse={isViewing}
          />
          {camera?.aiRunning ? <StatusBadge label="AI Running" tone="warning" /> : null}
        </div>
      </div>

      {/* ── Overlay Toggle Bar ── */}
      {camera && (
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={handleToggleRegion}
            className={`inline-flex h-10 items-center gap-2 rounded-xl border px-4 text-sm font-semibold transition ${
              overlayState.show_region
                ? 'border-cyan-500 bg-cyan-500/10 text-cyan-700 shadow-[0_0_12px_rgba(6,182,212,0.2)]'
                : 'border-neutral-300 bg-white text-neutral-600 hover:bg-neutral-100'
            }`}
          >
            <Layers className="h-4 w-4" />
            Region
            <span
              className={`ml-1 inline-block h-2 w-2 rounded-full ${
                overlayState.show_region ? 'bg-cyan-500' : 'bg-neutral-300'
              }`}
            />
          </button>
          <button
            type="button"
            onClick={handleToggleBbox}
            className={`inline-flex h-10 items-center gap-2 rounded-xl border px-4 text-sm font-semibold transition ${
              overlayState.show_bbox
                ? 'border-orange-400 bg-orange-400/10 text-orange-600 shadow-[0_0_12px_rgba(251,146,60,0.2)]'
                : 'border-neutral-300 bg-white text-neutral-600 hover:bg-neutral-100'
            }`}
          >
            <Scan className="h-4 w-4" />
            BBox
            <span
              className={`ml-1 inline-block h-2 w-2 rounded-full ${
                overlayState.show_bbox ? 'bg-orange-400' : 'bg-neutral-300'
              }`}
            />
          </button>
          {!camera.aiRunning && overlayState.show_bbox && (
            <span className="text-xs text-neutral-400">
              (AI chưa chạy — không có detection)
            </span>
          )}
        </div>
      )}

      <div className="mt-5">
        {!camera ? (
          <EmptyState
            icon={Camera}
            title="No camera selected"
            description="Pick a camera tab to inspect stream information and configure AI."
            className="min-h-[560px]"
          />
        ) : (
          <div className="rounded-[20px] border border-neutral-300 bg-white p-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
            <div
              className="relative aspect-video w-full overflow-hidden rounded-[16px] border border-black/70 bg-black"
            >
              {isViewing && activeStream ? (
                activeStream.mode === 'rtsp' ? (
                  <img
                    src={activeStream.streamUrl}
                    alt={`${camera.name} stream`}
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center p-6 text-center text-white">
                    <p className="text-sm text-neutral-300">Mock stream active</p>
                  </div>
                )
              ) : camera.health === 'offline' ? (
                <div className="flex h-full w-full items-center justify-center p-8 text-center text-white">
                  <div className="max-w-md space-y-4">
                    <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-[24px] bg-white/10 text-white">
                      <WifiOff className="h-8 w-8" />
                    </div>
                    <p className="text-sm text-neutral-300">{camera.name} is offline</p>
                  </div>
                </div>
              ) : (
                <div className="flex h-full w-full items-center justify-center p-8 text-center text-white">
                  <div className="max-w-lg">
                    <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-[24px] border border-white/20 bg-white/10 backdrop-blur-sm">
                      <MonitorPlay className="h-8 w-8" />
                    </div>
                    <h3 className="mt-5 text-2xl font-semibold text-white">
                      Ready to show {camera.name}
                    </h3>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}
