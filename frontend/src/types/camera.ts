export type AICoreKey =
  | 'fight'
  | 'weapon'
  | 'crowd'
  | 'trash'
  | 'parking'
  | 'encroachment'
  | 'fenceClimb'

export type CameraStatus = 'ready' | 'viewing' | 'running'

export type CameraHealth = 'online' | 'unstable' | 'offline'

export type CameraType = 'bullet' | 'ptz'

export interface PtzPreset {
  id: string
  name: string
  pan: number
  tilt: number
  zoom: number
}

export interface Camera {
  id: string
  name: string
  type: CameraType
  rtspUrl: string
  location: string
  description: string
  isViewing: boolean
  aiRunning: boolean
  selectedCores: AICoreKey[]
  status: CameraStatus
  health: CameraHealth
  ptzPresets: PtzPreset[]
  createdAt: string
}

export interface CameraFormValues {
  name: string
  rtspUrl: string
  location: string
  description: string
}

export interface StreamSession {
  cameraId: string
  streamUrl: string
  startedAt: string
  mode: 'mock' | 'rtsp'
}

export interface HomePositionState {
  home_set: boolean
  pan: number
  tilt: number
  zoom: number
}
