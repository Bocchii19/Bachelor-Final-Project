import type { AICoreKey, CameraHealth } from '@/types/camera'

export type EventSeverity = 'low' | 'medium' | 'high'

export interface EventItem {
  id: string
  cameraId: string
  cameraName: string
  core: AICoreKey
  message: string
  severity: EventSeverity
  createdAt: string
  isNew: boolean
  imageUrl?: string | null
}

export interface EventFilters {
  cameraId: string
  core: AICoreKey | 'all'
}

export interface RuntimeCameraContext {
  id: string
  name: string
  location: string
  selectedCores: AICoreKey[]
  aiRunning: boolean
  health: CameraHealth
}
