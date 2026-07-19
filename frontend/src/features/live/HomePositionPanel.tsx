import { Home, HousePlus } from 'lucide-react'

import type { HomePositionState } from '@/types/camera'

interface HomePositionPanelProps {
  state: HomePositionState
  isBusy: boolean
  onSetHome: () => void
  onGoHome: () => void
}

export function HomePositionPanel({ state, isBusy, onSetHome, onGoHome }: HomePositionPanelProps) {
  return (
    <div className="mt-5 rounded-[24px] border border-neutral-200 bg-neutral-50 p-4">
      <p className="text-sm font-semibold text-neutral-900">HOME Position (Fixed Position)</p>
      <p className="mt-2 text-sm text-green-700">
        {state.home_set ? '✓ HOME position set' : 'HOME position not set'}
      </p>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={onSetHome}
          disabled={isBusy}
          className="inline-flex h-12 w-1/2 items-center justify-center gap-2 rounded-[14px] border border-neutral-300 bg-white px-3 text-sm font-semibold text-neutral-900 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <HousePlus className="h-4 w-4" />
          Set as HOME
        </button>
        <button
          type="button"
          onClick={onGoHome}
          disabled={isBusy || !state.home_set}
          className="inline-flex h-12 w-1/2 items-center justify-center gap-2 rounded-[14px] border border-neutral-300 bg-white px-3 text-sm font-semibold text-neutral-900 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Home className="h-4 w-4" />
          Go to HOME
        </button>
      </div>

      <p className="mt-3 text-sm text-neutral-700">
        Steps: P:{state.pan} T:{state.tilt} Z:{state.zoom}
      </p>
    </div>
  )
}
