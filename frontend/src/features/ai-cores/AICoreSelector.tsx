import { Check, Sparkles } from 'lucide-react'

import { StatusBadge } from '@/components/ui/StatusBadge'
import { AI_CORE_ICONS } from '@/features/ai-cores/coreIcons'
import { AI_CORE_DEFINITIONS } from '@/mocks/aiCores'
import type { AICoreKey, CameraHealth } from '@/types/camera'
import { cn } from '@/utils/cn'

interface AICoreSelectorProps {
  selectedCores: AICoreKey[]
  disabled?: boolean
  aiRunning?: boolean
  aiStopping?: boolean
  health?: CameraHealth
  onToggle: (core: AICoreKey) => void
}

export function AICoreSelector({
  selectedCores,
  disabled = false,
  aiRunning = false,
  aiStopping = false,
  health = 'online',
  onToggle,
}: AICoreSelectorProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-neutral-950">Tính năng AI</h3>
          <p className="mt-1 text-xs uppercase tracking-[0.16em] text-neutral-500">
            Per-camera setup
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge label={`${selectedCores.length}/${AI_CORE_DEFINITIONS.length}`} tone="info" compact />
          {aiStopping ? (
            <StatusBadge label="Stopping" tone="warning" pulse compact />
          ) : aiRunning ? (
            <StatusBadge label="Running" tone="accent" pulse compact />
          ) : null}
        </div>
      </div>

      <div className="space-y-2.5">
        {AI_CORE_DEFINITIONS.map((core) => {
          const isActive = selectedCores.includes(core.key)
          const Icon = AI_CORE_ICONS[core.key]

          return (
            <button
              key={core.key}
              type="button"
              onClick={() => onToggle(core.key)}
              disabled={disabled}
              className={cn(
                'flex w-full items-center gap-3 rounded-[22px] border px-3.5 py-3 text-left transition',
                isActive
                  ? 'border-black bg-white shadow-[0_12px_24px_rgba(15,23,42,0.10)]'
                  : 'border-neutral-300 bg-white hover:border-neutral-400 hover:bg-neutral-50',
                disabled && 'cursor-not-allowed opacity-60',
              )}
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-black text-white">
                <Icon className="h-4 w-4" />
              </div>

              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold leading-5 text-neutral-950">{core.label}</p>
                <p className="mt-1 text-[11px] uppercase tracking-[0.16em] text-neutral-500">
                  {core.shortLabel}
                </p>
              </div>

              <div
                className={cn(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition',
                  isActive
                    ? 'border-black bg-black text-white'
                    : 'border-neutral-400 bg-white text-transparent',
                )}
              >
                <Check className="h-4 w-4" />
              </div>
            </button>
          )
        })}
      </div>

      {health === 'offline' ? (
        <div className="flex items-center gap-2 rounded-2xl border border-neutral-300 bg-neutral-100 px-3 py-2 text-sm text-neutral-700">
          <Sparkles className="h-4 w-4" />
          Camera offline. Configuration can be edited, but `Run` remains disabled.
        </div>
      ) : null}
    </div>
  )
}
