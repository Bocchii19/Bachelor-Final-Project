import { useState } from 'react'

import {
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Home,
  ZoomIn,
  ZoomOut,
  Crosshair,
} from 'lucide-react'

import { cn } from '@/utils/cn'

interface PtzControlPanelProps {
  onPtzMove: (direction: 'up' | 'down' | 'left' | 'right' | 'home') => void
  onZoom: (action: 'in' | 'out') => void
}

export function PtzControlPanel({
  onPtzMove,
  onZoom,
}: PtzControlPanelProps) {
  const [activeDirection, setActiveDirection] = useState<string | null>(null)

  const handleDirectionPress = (direction: 'up' | 'down' | 'left' | 'right' | 'home') => {
    setActiveDirection(direction)
    onPtzMove(direction)
    setTimeout(() => setActiveDirection(null), 200)
  }

  const directionBtnClass = (dir: string) =>
    cn(
      'flex h-11 w-11 items-center justify-center rounded-xl border transition-all duration-150',
      activeDirection === dir
        ? 'border-neutral-900 bg-neutral-900 text-white scale-95 shadow-lg'
        : 'border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-100 hover:border-neutral-400 active:scale-95',
    )

  return (
    <div className="mt-5 rounded-[24px] border border-neutral-200 bg-gradient-to-b from-white to-neutral-50 p-4 shadow-sm">
      <div className="flex items-center gap-2 border-b border-neutral-200 pb-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-neutral-900 text-white">
          <Crosshair className="h-4 w-4" />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-neutral-500">
            PTZ Control
          </p>
        </div>
      </div>

      {/* Directional pad */}
      <div className="mt-4 flex flex-col items-center gap-1">
        {/* Up */}
        <button
          type="button"
          onClick={() => handleDirectionPress('up')}
          className={directionBtnClass('up')}
          aria-label="Pan up"
        >
          <ArrowUp className="h-4 w-4" />
        </button>

        {/* Left - Home - Right */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => handleDirectionPress('left')}
            className={directionBtnClass('left')}
            aria-label="Pan left"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => handleDirectionPress('home')}
            className={cn(
              'flex h-11 w-11 items-center justify-center rounded-xl border transition-all duration-150',
              activeDirection === 'home'
                ? 'border-neutral-900 bg-neutral-900 text-white scale-95'
                : 'border-neutral-400 bg-neutral-100 text-neutral-700 hover:bg-neutral-200 active:scale-95',
            )}
            aria-label="Home position"
          >
            <Home className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => handleDirectionPress('right')}
            className={directionBtnClass('right')}
            aria-label="Pan right"
          >
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>

        {/* Down */}
        <button
          type="button"
          onClick={() => handleDirectionPress('down')}
          className={directionBtnClass('down')}
          aria-label="Pan down"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      </div>

      {/* Zoom controls */}
      <div className="mt-4 flex items-center justify-center gap-2">
        <button
          type="button"
          onClick={() => onZoom('out')}
          className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl border border-neutral-300 bg-white text-sm font-medium text-neutral-700 transition hover:bg-neutral-100 active:scale-[0.97]"
        >
          <ZoomOut className="h-4 w-4" />
          Zoom −
        </button>
        <button
          type="button"
          onClick={() => onZoom('in')}
          className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl border border-neutral-300 bg-white text-sm font-medium text-neutral-700 transition hover:bg-neutral-100 active:scale-[0.97]"
        >
          <ZoomIn className="h-4 w-4" />
          Zoom +
        </button>
      </div>
    </div>
  )
}
