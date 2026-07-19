import type { Camera, CameraStatus } from '@/types/camera'

export function deriveCameraStatus(camera: Pick<Camera, 'isViewing' | 'aiRunning'>): CameraStatus {
  if (camera.isViewing) {
    return 'viewing'
  }

  if (camera.aiRunning) {
    return 'running'
  }

  return 'ready'
}

export function normalizeCamera(camera: Camera): Camera {
  return {
    ...camera,
    type: camera.type ?? 'bullet',
    description: camera.description ?? '',
    ptzPresets: camera.ptzPresets ?? [],
    status: deriveCameraStatus(camera),
  }
}

export function cloneCamera(camera: Camera): Camera {
  return {
    ...camera,
    selectedCores: [...camera.selectedCores],
    ptzPresets: [...(camera.ptzPresets ?? [])],
  }
}
