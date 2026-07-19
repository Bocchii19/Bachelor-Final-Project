import { Activity, Cpu, Radar, Wifi } from 'lucide-react'

import { Panel } from '@/components/ui/Panel'
import { apiConfig } from '@/services/config'

interface PageHeaderProps {
  totalCameras: number
  runningCameras: number
  viewingCameraCount: number
}

export function PageHeader({
  totalCameras,
  runningCameras,
  viewingCameraCount,
}: PageHeaderProps) {
  return (
    <Panel className="relative overflow-hidden">
      <div className="absolute right-0 top-0 h-40 w-40 rounded-full bg-accent/10 blur-3xl" />
      <div className="absolute bottom-0 left-0 h-32 w-32 rounded-full bg-warning/10 blur-3xl" />

      <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-4">
          <div className="inline-flex items-center gap-2 rounded-full border border-accent/20 bg-accent/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.32em] text-glow">
            <Radar className="h-4 w-4" />
            Surveillance System
          </div>
          <div className="space-y-3">
            <h1 className="max-w-3xl text-3xl font-semibold tracking-tight text-slate-50 md:text-4xl">
              Multi-camera AI dashboard with mock stream orchestration and realtime event feed.
            </h1>
            <p className="max-w-3xl text-sm leading-7 text-slate-400 md:text-base">
              Frontend-first demo: camera tabs, fake live stream, AI core configuration,
              persisted mock data, and event simulation ready for a future backend.
            </p>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
              <Activity className="h-4 w-4" />
              Cameras
            </div>
            <div className="mt-4 text-3xl font-semibold text-slate-50">{totalCameras}</div>
            <p className="mt-1 text-sm text-slate-400">Tabs ready for live or config flow.</p>
          </div>
          <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
              <Cpu className="h-4 w-4" />
              AI Running
            </div>
            <div className="mt-4 text-3xl font-semibold text-slate-50">{runningCameras}</div>
            <p className="mt-1 text-sm text-slate-400">Only running cameras emit fake events.</p>
          </div>
          <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
              <Wifi className="h-4 w-4" />
              Stream Session
            </div>
            <div className="mt-4 text-3xl font-semibold text-slate-50">{viewingCameraCount}</div>
            <p className="mt-1 text-sm text-slate-400 font-mono">{apiConfig.wsUrl}</p>
          </div>
        </div>
      </div>

      <div className="relative mt-5 flex flex-wrap items-center gap-3 text-xs text-slate-400">
        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 font-mono">
          API: {apiConfig.baseUrl}
        </span>
        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
          Mock mode enabled
        </span>
        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
          Docker/LAN ready on port 8080
        </span>
      </div>
    </Panel>
  )
}
