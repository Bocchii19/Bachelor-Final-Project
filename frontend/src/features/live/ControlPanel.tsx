import {
  Camera,
  Eye,
  Pencil,
  Play,
  Square,
  Trash2,
} from 'lucide-react'

import { Panel } from '@/components/ui/Panel'
import { AICoreSelector } from '@/features/ai-cores/AICoreSelector'
import { HomePositionPanel } from '@/features/live/HomePositionPanel'
import { PtzControlPanel } from '@/features/live/PtzControlPanel'
import type { AICoreKey, Camera as CameraItem, HomePositionState } from '@/types/camera'

interface ControlPanelProps {
  camera: CameraItem | null
  pendingAction: string | null
  onShow: () => void
  onStop: () => void
  onRun: () => void
  onStopRun: () => void
  onEdit: () => void
  onDelete: () => void
  onToggleCore: (core: AICoreKey) => void
  onPtzMove: (direction: 'up' | 'down' | 'left' | 'right' | 'home') => void
  onZoom: (action: 'in' | 'out') => void
  homePositionState: HomePositionState
  onSetHomePosition: () => void
  onGotoHomePosition: () => void
}

export function ControlPanel({
  camera,
  pendingAction,
  onShow,
  onStop,
  onRun,
  onStopRun,
  onEdit,
  onDelete,
  onToggleCore,
  onPtzMove,
  onZoom,
  homePositionState,
  onSetHomePosition,
  onGotoHomePosition,
}: ControlPanelProps) {
  const isBusy = pendingAction !== null

  return (
    <Panel className="flex h-full min-h-[720px] flex-col lg:min-h-[640px]">
      {camera ? (
        <>
          <div className="flex items-start justify-between gap-4 border-b border-neutral-200 pb-5">
            <div>
              <p className="text-[22px] font-semibold tracking-[0.14em] text-black">
                CÀI ĐẶT
              </p>
            </div>

            <div className="flex gap-2">
              <button
                type="button"
                onClick={onEdit}
                className="inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-neutral-300 bg-white text-neutral-800 transition hover:bg-neutral-100"
                aria-label="Edit camera"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={onDelete}
                className="inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-black bg-black text-white transition hover:bg-neutral-800"
                aria-label="Delete camera"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="mt-5 flex items-center gap-3">
            <button
              type="button"
              onClick={onShow}
              disabled={pendingAction === 'show' || pendingAction === 'stop'}
              className="inline-flex h-14 w-1/2 items-center justify-center gap-2 rounded-[22px] border border-black bg-black px-4 text-sm font-semibold text-white shadow-[0_14px_28px_rgba(15,23,42,0.14)] transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Eye className="h-4 w-4" />
              {pendingAction === 'show' ? 'Opening...' : 'Show'}
            </button>

            <button
              type="button"
              onClick={onStop}
              disabled={pendingAction === 'stop' || !camera.isViewing}
              className="inline-flex h-14 w-1/2 items-center justify-center gap-2 rounded-[22px] border border-neutral-300 bg-white px-4 text-sm font-semibold text-neutral-900 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Square className="h-4 w-4" />
              {pendingAction === 'stop' ? 'Stopping All...' : 'Stop All'}
            </button>
          </div>

          {/* PTZ Controls — only shown for PTZ cameras */}
          {camera.type === 'ptz' && (
            <>
              <PtzControlPanel onPtzMove={onPtzMove} onZoom={onZoom} />
              <HomePositionPanel
                state={homePositionState}
                isBusy={isBusy}
                onSetHome={onSetHomePosition}
                onGoHome={onGotoHomePosition}
              />
            </>
          )}

          <div className="mt-5 flex-1 rounded-[28px] border border-neutral-200 bg-neutral-50/80 p-4">
            <AICoreSelector
              selectedCores={camera.selectedCores}
              aiRunning={camera.aiRunning}
              aiStopping={pendingAction === 'stop-ai'}
              health={camera.health}
              disabled={pendingAction === 'save' || pendingAction === 'delete'}
              onToggle={onToggleCore}
            />

            <div className="mt-5 flex items-center gap-3">
              <button
                type="button"
                onClick={onRun}
                disabled={
                  isBusy || camera.aiRunning || camera.selectedCores.length === 0 || camera.health === 'offline'
                }
                className="inline-flex h-14 w-1/2 items-center justify-center gap-2 rounded-[22px] border border-neutral-300 bg-white px-4 text-sm font-semibold text-neutral-900 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Play className="h-4 w-4" />
                {pendingAction === 'run' ? 'Deploying AI...' : camera.aiRunning ? 'Running' : 'Run'}
              </button>
              <button
                type="button"
                onClick={onStopRun}
                disabled={pendingAction === 'stop-ai' || !camera.aiRunning}
                className="inline-flex h-14 w-1/2 items-center justify-center gap-2 rounded-[22px] border border-neutral-300 bg-white px-4 text-sm font-semibold text-neutral-900 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Square className="h-4 w-4" />
                {pendingAction === 'stop-ai' ? 'Stopping...' : 'Stop'}
              </button>
            </div>

            <p className="mt-3 text-sm leading-6 text-neutral-600">
              `Stop All` (o tren) chi dung hien thi live stream. Nut `Stop` trong Tính năng AI chi dung
              thuat toan AI.
            </p>
          </div>
        </>
      ) : (
        <div className="flex h-full min-h-[520px] flex-col items-center justify-center text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-[24px] bg-black text-white shadow-[0_18px_28px_rgba(15,23,42,0.14)]">
            <Camera className="h-8 w-8" />
          </div>
          <h3 className="mt-5 text-xl font-semibold text-neutral-950">No active camera</h3>
          <p className="mt-3 max-w-sm text-sm leading-7 text-neutral-600">
            Select a camera tab or add a new camera to unlock operator controls, live view and AI
            configuration.
          </p>
        </div>
      )}
    </Panel>
  )
}
