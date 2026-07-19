import { DEFAULT_CAMERAS } from '@/mocks/cameras'
import { apiConfig } from '@/services/config'
import type {
  AICoreKey,
  Camera,
  CameraFormValues,
  HomePositionState,
  PtzPreset,
  StreamSession,
} from '@/types/camera'
import { cloneCamera, normalizeCamera } from '@/utils/cameras'
import { readStorage, writeStorage } from '@/utils/storage'

const CAMERA_STORAGE_KEY = 'surveillance-system:cameras-v3'
type ActionResult = { ok: boolean; message: string }
export type PtzActionResult = ActionResult & { homeState?: HomePositionState }
type PolygonPoint = { x: number; y: number }
export type PolygonConfigKey = 'treo-rao' | 'lan-chiem' | 'do-xe' | 'do-rac'

const DEFAULT_HOME_STATE: HomePositionState = {
  home_set: false,
  pan: 0,
  tilt: 0,
  zoom: 0,
}

function toHomeState(value: unknown): HomePositionState | undefined {
  if (!value || typeof value !== 'object') return undefined
  const data = value as Partial<HomePositionState>
  if (
    typeof data.home_set !== 'boolean' ||
    typeof data.pan !== 'number' ||
    typeof data.tilt !== 'number' ||
    typeof data.zoom !== 'number'
  ) {
    return undefined
  }
  return data
}

function isRemovedDefaultCamera(camera: Pick<Camera, 'id' | 'name'>) {
  return camera.id === 'bullet-4' || camera.name.trim().toLowerCase() === 'bullet 4'
}

function delay(duration = 220) {
  return new Promise((resolve) => window.setTimeout(resolve, duration))
}

function readCameras(): Camera[] {
  const storedCameras = readStorage<Camera[]>(CAMERA_STORAGE_KEY, [])
  if (storedCameras.length > 0) {
    const filtered = storedCameras
      .filter((camera) => !isRemovedDefaultCamera(camera))
      .map(normalizeCamera)
    if (filtered.length !== storedCameras.length) {
      writeStorage(CAMERA_STORAGE_KEY, filtered)
    }
    return filtered
  }

  const seededCameras = DEFAULT_CAMERAS.map(cloneCamera).map(normalizeCamera)
  writeStorage(CAMERA_STORAGE_KEY, seededCameras)
  return seededCameras
}

function persistCameras(cameras: Camera[]) {
  writeStorage(CAMERA_STORAGE_KEY, cameras.map(normalizeCamera))
}

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

export async function getCameras(): Promise<Camera[]> {
  await delay(160)
  return readCameras()
}

export async function addCamera(values: CameraFormValues): Promise<Camera> {
  await delay(260)

  const cameras = readCameras()
  const newCamera: Camera = normalizeCamera({
    id: `${slugify(values.name)}-${Math.random().toString(36).slice(2, 7)}`,
    name: values.name,
    type: 'bullet',
    rtspUrl: values.rtspUrl,
    location: values.location,
    description: values.description,
    isViewing: false,
    aiRunning: false,
    selectedCores: [],
    status: 'ready',
    health: 'online',
    ptzPresets: [],
    createdAt: new Date().toISOString(),
  })

  const nextCameras = [...cameras, newCamera]
  persistCameras(nextCameras)
  return newCamera
}

export async function updateCamera(
  cameraId: string,
  values: CameraFormValues,
): Promise<Camera> {
  await delay(240)

  const cameras = readCameras()
  let updatedCamera: Camera | null = null

  const nextCameras = cameras.map((camera) => {
    if (camera.id !== cameraId) {
      return camera
    }

    updatedCamera = normalizeCamera({
      ...camera,
      name: values.name,
      rtspUrl: values.rtspUrl,
      location: values.location,
      description: values.description,
    })

    return updatedCamera
  })

  if (!updatedCamera) {
    throw new Error('Camera not found')
  }

  persistCameras(nextCameras)
  return updatedCamera
}

export async function deleteCamera(cameraId: string) {
  await delay(220)

  const nextCameras = readCameras().filter((camera) => camera.id !== cameraId)
  persistCameras(nextCameras)
}

export async function showCamera(cameraId: string, rtspUrl: string): Promise<StreamSession> {
  const response = await fetch(`${apiConfig.baseUrl}/streams/show`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cameraId,
      rtspUrl,
    }),
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(body || `showCamera failed: ${response.status}`)
  }
  const data = (await response.json()) as StreamSession
  const backendRoot = apiConfig.baseUrl.replace(/\/api\/?$/, '')
  const cacheBust = encodeURIComponent(data.startedAt || new Date().toISOString())
  return {
    ...data,
    cameraId,
    mode: 'rtsp',
    streamUrl: `${backendRoot}/api/streams/${encodeURIComponent(cameraId)}/mjpeg?ts=${cacheBust}`,
  }
}

export async function stopCamera(cameraId: string) {
  try {
    await fetch(`${apiConfig.baseUrl}/streams/stop/${encodeURIComponent(cameraId)}`, {
      method: 'POST',
    })
  } catch {
    await delay(180)
  }
}

export async function ptzMove(
  cameraId: string,
  rtspUrl: string,
  direction: 'up' | 'down' | 'left' | 'right' | 'home',
): Promise<PtzActionResult> {
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ptz/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cameraId, rtspUrl, direction }),
    })
    if (!response.ok) {
      const body = await response.text()
      return { ok: false, message: `PTZ move failed: ${body || response.status}` }
    }
    const body = (await response.json()) as { homeState?: HomePositionState }
    return { ok: true, message: `PTZ move: ${direction}`, homeState: toHomeState(body.homeState) }
  } catch (e) {
    return { ok: false, message: `PTZ move error: ${(e as Error).message}` }
  }
}

export async function ptzZoom(
  cameraId: string,
  rtspUrl: string,
  action: 'in' | 'out',
): Promise<PtzActionResult> {
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ptz/zoom`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cameraId, rtspUrl, action }),
    })
    if (!response.ok) {
      const body = await response.text()
      return { ok: false, message: `PTZ zoom failed: ${body || response.status}` }
    }
    const body = (await response.json()) as { homeState?: HomePositionState }
    return { ok: true, message: `PTZ zoom: ${action}`, homeState: toHomeState(body.homeState) }
  } catch (e) {
    return { ok: false, message: `PTZ zoom error: ${(e as Error).message}` }
  }
}

export async function ptzGotoPreset(
  cameraId: string,
  rtspUrl: string,
  preset: number,
): Promise<PtzActionResult> {
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ptz/preset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cameraId, rtspUrl, preset }),
    })
    if (!response.ok) {
      const body = await response.text()
      return { ok: false, message: `PTZ preset failed: ${body || response.status}` }
    }
    const body = (await response.json()) as { homeState?: HomePositionState }
    return {
      ok: true,
      message: `PTZ goto preset ${preset}`,
      homeState: toHomeState(body.homeState),
    }
  } catch (e) {
    return { ok: false, message: `PTZ preset error: ${(e as Error).message}` }
  }
}

export async function ptzSetHome(cameraId: string, rtspUrl: string, password: string): Promise<PtzActionResult> {
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ptz/set_home`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cameraId, rtspUrl, preset: 255, password }),
    })
    if (!response.ok) {
      const body = await response.text()
      // Parse detail from JSON error response if possible
      try {
        const err = JSON.parse(body)
        if (err.detail) return { ok: false, message: err.detail }
      } catch { /* ignore */ }
      return { ok: false, message: `Set HOME failed: ${body || response.status}` }
    }
    const body = (await response.json()) as { homeState?: HomePositionState }
    return { ok: true, message: 'HOME position saved', homeState: toHomeState(body.homeState) }
  } catch (e) {
    return { ok: false, message: `Set HOME error: ${(e as Error).message}` }
  }
}

export async function ptzGotoHome(cameraId: string, rtspUrl: string): Promise<PtzActionResult> {
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ptz/goto_home`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cameraId, rtspUrl, preset: 255 }),
    })
    if (!response.ok) {
      const body = await response.text()
      return { ok: false, message: `Go HOME failed: ${body || response.status}` }
    }
    const body = (await response.json()) as { homeState?: HomePositionState }
    return { ok: true, message: 'Moved to HOME position', homeState: toHomeState(body.homeState) }
  } catch (e) {
    return { ok: false, message: `Go HOME error: ${(e as Error).message}` }
  }
}

export async function ptzGetHomeStatus(
  cameraId: string,
  rtspUrl: string,
): Promise<HomePositionState> {
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ptz/home/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cameraId, rtspUrl }),
    })
    if (!response.ok) {
      throw new Error(`status ${response.status}`)
    }
    const body = (await response.json()) as { homeState?: HomePositionState }
    return toHomeState(body.homeState) ?? DEFAULT_HOME_STATE
  } catch {
    return DEFAULT_HOME_STATE
  }
}

export async function savePolygonConfig(
  cameraId: string,
  cameraName: string,
  configKey: PolygonConfigKey,
  polygon: PolygonPoint[],
  rtspUrl: string,
): Promise<ActionResult> {
  try {
    const response = await fetch(`${apiConfig.baseUrl}/configs/polygon`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cameraId,
        cameraName,
        configKey,
        polygon,
        width: 1920,
        height: 1080,
        rtspUrl: rtspUrl.trim(),
      }),
    })
    if (!response.ok) {
      const body = await response.text()
      return { ok: false, message: `Lưu cấu hình thất bại: ${body || response.status}` }
    }
    return { ok: true, message: 'Đã lưu polygon vào configs.yaml (tọa độ 1920×1080)' }
  } catch (e) {
    return { ok: false, message: `Lỗi lưu cấu hình: ${(e as Error).message}` }
  }
}

export async function saveCameraCoreConfig(
  cameraId: string,
  cores: AICoreKey[],
): Promise<Camera> {
  await delay(140)

  const cameras = readCameras()
  let updatedCamera: Camera | null = null

  const nextCameras = cameras.map((camera) => {
    if (camera.id !== cameraId) {
      return camera
    }

    updatedCamera = normalizeCamera({
      ...camera,
      selectedCores: [...cores],
    })

    return updatedCamera
  })

  if (!updatedCamera) {
    throw new Error('Camera not found')
  }

  persistCameras(nextCameras)
  return updatedCamera
}

export async function runCameraCores(cameraId: string): Promise<Camera> {
  const cameras = readCameras()
  const camera = cameras.find((c) => c.id === cameraId)
  if (!camera) throw new Error('Camera not found')

  // Call backend to start AI detection
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ai/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cores: camera.selectedCores,
        noPtz: false,
      }),
    })
    if (!response.ok) {
      const body = await response.text()
      throw new Error(body || `AI start failed: ${response.status}`)
    }
  } catch (e) {
    throw new Error(`Failed to start AI: ${(e as Error).message}`)
  }

  // Update local state
  let updatedCamera: Camera | null = null
  const nextCameras = cameras.map((c) => {
    if (c.id !== cameraId) return c
    updatedCamera = normalizeCamera({ ...c, aiRunning: true })
    return updatedCamera
  })
  if (!updatedCamera) throw new Error('Camera not found')
  persistCameras(nextCameras)
  return updatedCamera
}

export async function stopCameraCores(cameraId: string): Promise<Camera> {
  // Call backend to stop AI detection
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ai/stop`, {
      method: 'POST',
    })
    if (!response.ok) {
      const body = await response.text()
      console.warn('AI stop response:', body)
    }
  } catch (e) {
    console.warn('AI stop error:', (e as Error).message)
  }

  // Update local state
  const cameras = readCameras()
  let updatedCamera: Camera | null = null
  const nextCameras = cameras.map((c) => {
    if (c.id !== cameraId) return c
    updatedCamera = normalizeCamera({ ...c, aiRunning: false })
    return updatedCamera
  })
  if (!updatedCamera) throw new Error('Camera not found')
  persistCameras(nextCameras)
  return updatedCamera
}

/**
 * Query backend AI status to sync frontend state.
 * Returns true if AI is currently running.
 */
export async function getAiStatus(): Promise<boolean> {
  try {
    const response = await fetch(`${apiConfig.baseUrl}/ai/status`)
    if (response.ok) {
      const data = await response.json()
      return data.running === true
    }
  } catch {
    // Backend not reachable — assume AI is not running
  }
  return false
}

export async function savePtzPreset(
  cameraId: string,
  presetName: string,
): Promise<Camera> {
  await delay(140)

  const cameras = readCameras()
  let updatedCamera: Camera | null = null

  const nextCameras = cameras.map((camera) => {
    if (camera.id !== cameraId) {
      return camera
    }

    const newPreset: PtzPreset = {
      id: `preset-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
      name: presetName,
      pan: Math.round(Math.random() * 360),
      tilt: Math.round(Math.random() * 90 - 45),
      zoom: Math.round(Math.random() * 10) + 1,
    }

    updatedCamera = normalizeCamera({
      ...camera,
      ptzPresets: [...camera.ptzPresets, newPreset],
    })

    return updatedCamera
  })

  if (!updatedCamera) {
    throw new Error('Camera not found')
  }

  persistCameras(nextCameras)
  return updatedCamera
}

export async function deletePtzPreset(
  cameraId: string,
  presetId: string,
): Promise<Camera> {
  await delay(120)

  const cameras = readCameras()
  let updatedCamera: Camera | null = null

  const nextCameras = cameras.map((camera) => {
    if (camera.id !== cameraId) {
      return camera
    }

    updatedCamera = normalizeCamera({
      ...camera,
      ptzPresets: camera.ptzPresets.filter((p) => p.id !== presetId),
    })

    return updatedCamera
  })

  if (!updatedCamera) {
    throw new Error('Camera not found')
  }

  persistCameras(nextCameras)
  return updatedCamera
}

// ── Overlay API ───────────────────────────────────────────────────────────

export interface OverlayState {
  show_region: boolean
  show_bbox: boolean
}

export async function toggleOverlay(
  cameraId: string,
  showRegion?: boolean,
  showBbox?: boolean,
): Promise<OverlayState> {
  try {
    const body: Record<string, unknown> = { cameraId }
    if (showRegion !== undefined) body.showRegion = showRegion
    if (showBbox !== undefined) body.showBbox = showBbox

    const response = await fetch(`${apiConfig.baseUrl}/overlay/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      return { show_region: false, show_bbox: false }
    }
    const data = (await response.json()) as OverlayState
    return { show_region: data.show_region ?? false, show_bbox: data.show_bbox ?? false }
  } catch {
    return { show_region: false, show_bbox: false }
  }
}

export async function getOverlayStatus(cameraId: string): Promise<OverlayState> {
  try {
    const response = await fetch(
      `${apiConfig.baseUrl}/overlay/status/${encodeURIComponent(cameraId)}`,
    )
    if (!response.ok) {
      return { show_region: false, show_bbox: false }
    }
    const data = (await response.json()) as OverlayState
    return { show_region: data.show_region ?? false, show_bbox: data.show_bbox ?? false }
  } catch {
    return { show_region: false, show_bbox: false }
  }
}
