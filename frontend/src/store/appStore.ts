import { create } from 'zustand'

import * as cameraService from '@/services/cameraService'
import * as eventService from '@/services/eventService'
import type { AICoreKey, Camera, CameraFormValues, StreamSession } from '@/types/camera'
import type { EventFilters, EventItem } from '@/types/event'
import { deriveCameraStatus } from '@/utils/cameras'
import { trimText } from '@/utils/format'

type PendingAction = 'bootstrap' | 'show' | 'stop' | 'run' | 'stop-ai' | 'save' | 'delete' | null

type ActionResult =
  | { ok: true; message: string }
  | { ok: false; message: string }

interface AppStore {
  cameras: Camera[]
  events: EventItem[]
  selectedCameraId: string | null
  activeStream: StreamSession | null
  eventFilters: EventFilters
  isBootstrapped: boolean
  pendingAction: PendingAction
  bootstrap: () => Promise<void>
  setSelectedCamera: (cameraId: string) => void
  setEventFilters: (filters: Partial<EventFilters>) => void
  toggleCoreSelection: (core: AICoreKey) => Promise<void>
  showSelectedCamera: () => Promise<ActionResult>
  stopSelectedCamera: () => Promise<ActionResult>
  runSelectedCameraCores: () => Promise<ActionResult>
  stopSelectedCameraCores: () => Promise<ActionResult>
  addCamera: (values: CameraFormValues) => Promise<ActionResult>
  updateCamera: (cameraId: string, values: CameraFormValues) => Promise<ActionResult>
  deleteCamera: (cameraId: string) => Promise<ActionResult>
  savePtzPreset: (cameraId: string, name: string) => Promise<ActionResult>
  deletePtzPreset: (cameraId: string, presetId: string) => Promise<ActionResult>
  prependEvent: (event: EventItem) => void
  markEventSeen: (eventId: string) => void
  clearEvents: () => void
}

const initialFilters: EventFilters = {
  cameraId: 'all',
  core: 'all',
}

function sanitizeCameraValues(values: CameraFormValues): CameraFormValues {
  return {
    name: trimText(values.name),
    rtspUrl: trimText(values.rtspUrl),
    location: trimText(values.location),
    description: trimText(values.description),
  }
}

function isCameraNameTaken(cameras: Camera[], name: string, excludeId?: string) {
  return cameras.some(
    (camera) =>
      camera.id !== excludeId &&
      camera.name.trim().toLowerCase() === name.trim().toLowerCase(),
  )
}

function updateCameraList(cameras: Camera[], nextCamera: Camera) {
  return cameras.map((camera) => (camera.id === nextCamera.id ? nextCamera : camera))
}

function withViewingState(cameras: Camera[], activeCameraId: string | null) {
  return cameras.map((camera) => {
    const isViewing = camera.id === activeCameraId

    return {
      ...camera,
      isViewing,
      status: deriveCameraStatus({
        isViewing,
        aiRunning: camera.aiRunning,
      }),
    }
  })
}

function persistEventSnapshot(events: EventItem[]) {
  eventService.persistEvents(events)
}

export const useAppStore = create<AppStore>((set, get) => ({
  cameras: [],
  events: [],
  selectedCameraId: null,
  activeStream: null,
  eventFilters: initialFilters,
  isBootstrapped: false,
  pendingAction: null,

  bootstrap: async () => {
    if (get().isBootstrapped) {
      return
    }

    set({ pendingAction: 'bootstrap' })

    const [cameras, events, aiRunning] = await Promise.all([
      cameraService.getCameras(),
      eventService.getEvents(),
      cameraService.getAiStatus(),
    ])

    set({
      cameras: cameras.map((c) => ({ ...c, aiRunning })),
      events,
      selectedCameraId: cameras[0]?.id ?? null,
      isBootstrapped: true,
      pendingAction: null,
    })
  },

  setSelectedCamera: (cameraId) => {
    const { cameras, activeStream } = get()
    const currentViewingCamera = cameras.find((camera) => camera.isViewing)

    if (currentViewingCamera && currentViewingCamera.id !== cameraId) {
      void cameraService.stopCamera(currentViewingCamera.id)
    }

    set({
      cameras:
        currentViewingCamera && currentViewingCamera.id !== cameraId
          ? withViewingState(cameras, null)
          : cameras,
      selectedCameraId: cameraId,
      activeStream:
        activeStream && activeStream.cameraId !== cameraId ? null : activeStream,
    })
  },

  setEventFilters: (filters) => {
    set((state) => ({
      eventFilters: {
        ...state.eventFilters,
        ...filters,
      },
    }))
  },

  toggleCoreSelection: async (core) => {
    const { selectedCameraId, cameras } = get()
    if (!selectedCameraId) {
      return
    }

    const selectedCamera = cameras.find((camera) => camera.id === selectedCameraId)
    if (!selectedCamera) {
      return
    }

    const nextCores = selectedCamera.selectedCores.includes(core)
      ? selectedCamera.selectedCores.filter((item) => item !== core)
      : [...selectedCamera.selectedCores, core]

    const nextCamera = {
      ...selectedCamera,
      selectedCores: nextCores,
      status: deriveCameraStatus(selectedCamera),
    }

    set({
      cameras: updateCameraList(cameras, nextCamera),
    })

    try {
      await cameraService.saveCameraCoreConfig(selectedCameraId, nextCores)
    } catch {
      set({
        cameras,
      })
    }
  },

  showSelectedCamera: async () => {
    const { selectedCameraId, cameras } = get()
    if (!selectedCameraId) {
      return { ok: false, message: 'Select a camera first.' }
    }

    const selectedCamera = cameras.find((camera) => camera.id === selectedCameraId)
    if (!selectedCamera) {
      return { ok: false, message: 'Camera not found.' }
    }

    set({ pendingAction: 'show' })
    try {
      const stream = await cameraService.showCamera(selectedCameraId, selectedCamera.rtspUrl)
      const nextCameras = withViewingState(cameras, selectedCameraId)

      set({
        cameras: nextCameras,
        activeStream: stream,
        pendingAction: null,
      })

      return { ok: true, message: `Live view opened for ${selectedCamera.name}.` }
    } catch (error) {
      set({ pendingAction: null })
      return {
        ok: false,
        message: `Cannot open RTSP stream for ${selectedCamera.name}: ${(error as Error).message}`,
      }
    }
  },

  stopSelectedCamera: async () => {
    const { selectedCameraId, cameras, activeStream } = get()
    if (!selectedCameraId) {
      return { ok: false, message: 'Select a camera first.' }
    }

    const selectedCamera = cameras.find((camera) => camera.id === selectedCameraId)
    if (!selectedCamera || !selectedCamera.isViewing || !activeStream) {
      return { ok: false, message: 'No live view is currently active.' }
    }

    set({ pendingAction: 'stop' })

    await cameraService.stopCamera(selectedCameraId)
    set({
      cameras: withViewingState(cameras, null),
      activeStream: null,
      pendingAction: null,
    })

    return { ok: true, message: `Live view stopped for ${selectedCamera.name}.` }
  },

  runSelectedCameraCores: async () => {
    const { selectedCameraId, cameras } = get()
    if (!selectedCameraId) {
      return { ok: false, message: 'Select a camera first.' }
    }

    const selectedCamera = cameras.find((camera) => camera.id === selectedCameraId)
    if (!selectedCamera) {
      return { ok: false, message: 'Camera not found.' }
    }

    if (selectedCamera.health === 'offline') {
      return { ok: false, message: `${selectedCamera.name} is offline and cannot run AI.` }
    }

    if (selectedCamera.selectedCores.length === 0) {
      return { ok: false, message: 'Pick at least one AI core before running.' }
    }

    set({ pendingAction: 'run' })

    try {
      await cameraService.saveCameraCoreConfig(selectedCamera.id, selectedCamera.selectedCores)
      await cameraService.runCameraCores(selectedCamera.id)

      // AI backend runs for ALL cameras — mark all as aiRunning
      set((state) => ({
        cameras: state.cameras.map((c) => ({ ...c, aiRunning: true })),
        pendingAction: null,
      }))

      return {
        ok: true,
        message: `AI detection started for all cameras.`,
      }
    } catch (error) {
      set({ pendingAction: null })
      return { ok: false, message: `Failed to start AI: ${(error as Error).message}` }
    }
  },

  stopSelectedCameraCores: async () => {
    const { cameras } = get()

    // Check if any camera has AI running
    const anyRunning = cameras.some((c) => c.aiRunning)
    if (!anyRunning) {
      return { ok: false, message: 'AI is not currently running.' }
    }

    set({ pendingAction: 'stop-ai' })

    try {
      // Stop for any camera — backend stops the single global AI instance
      const firstRunning = cameras.find((c) => c.aiRunning)
      if (firstRunning) {
        await cameraService.stopCameraCores(firstRunning.id)
      }

      // Mark ALL cameras as not running
      set((state) => ({
        cameras: state.cameras.map((c) => ({ ...c, aiRunning: false })),
        pendingAction: null,
      }))

      return { ok: true, message: 'AI detection stopped.' }
    } catch (error) {
      set({ pendingAction: null })
      return { ok: false, message: `Failed to stop AI: ${(error as Error).message}` }
    }
  },

  addCamera: async (values) => {
    const sanitizedValues = sanitizeCameraValues(values)
    const { cameras } = get()

    if (isCameraNameTaken(cameras, sanitizedValues.name)) {
      return { ok: false, message: 'Camera name already exists.' }
    }

    set({ pendingAction: 'save' })

    const newCamera = await cameraService.addCamera(sanitizedValues)
    set((state) => ({
      cameras: [...state.cameras, newCamera],
      selectedCameraId: newCamera.id,
      pendingAction: null,
    }))

    return { ok: true, message: `${newCamera.name} added successfully.` }
  },

  updateCamera: async (cameraId, values) => {
    const sanitizedValues = sanitizeCameraValues(values)
    const { cameras } = get()

    if (isCameraNameTaken(cameras, sanitizedValues.name, cameraId)) {
      return { ok: false, message: 'Camera name already exists.' }
    }

    set({ pendingAction: 'save' })

    const updatedCamera = await cameraService.updateCamera(cameraId, sanitizedValues)
    set((state) => ({
      cameras: updateCameraList(state.cameras, updatedCamera),
      pendingAction: null,
    }))

    return { ok: true, message: `${updatedCamera.name} updated successfully.` }
  },

  deleteCamera: async (cameraId) => {
    const { cameras, selectedCameraId, events, eventFilters, activeStream } = get()
    const targetCamera = cameras.find((camera) => camera.id === cameraId)

    if (!targetCamera) {
      return { ok: false, message: 'Camera not found.' }
    }

    set({ pendingAction: 'delete' })

    await cameraService.deleteCamera(cameraId)

    const nextCameras = cameras.filter((camera) => camera.id !== cameraId)
    const nextEvents = events.filter((event) => event.cameraId !== cameraId)
    const nextSelectedCameraId =
      selectedCameraId === cameraId ? nextCameras[0]?.id ?? null : selectedCameraId

    persistEventSnapshot(nextEvents)

    set({
      cameras: nextCameras,
      events: nextEvents,
      selectedCameraId: nextSelectedCameraId,
      eventFilters: {
        ...eventFilters,
        cameraId:
          eventFilters.cameraId === cameraId && nextCameras.length > 0
            ? 'all'
            : eventFilters.cameraId,
      },
      activeStream: activeStream?.cameraId === cameraId ? null : activeStream,
      pendingAction: null,
    })

    return { ok: true, message: `${targetCamera.name} removed from the dashboard.` }
  },

  prependEvent: (event) => {
    set((state) => {
      const nextEvents = [event, ...state.events].slice(0, 120)
      persistEventSnapshot(nextEvents)

      return {
        events: nextEvents,
      }
    })

    window.setTimeout(() => {
      get().markEventSeen(event.id)
    }, 8000)
  },

  markEventSeen: (eventId) => {
    set((state) => {
      const nextEvents = state.events.map((event) =>
        event.id === eventId ? { ...event, isNew: false } : event,
      )

      persistEventSnapshot(nextEvents)
      return {
        events: nextEvents,
      }
    })
  },

  savePtzPreset: async (cameraId, name) => {
    try {
      const updatedCamera = await cameraService.savePtzPreset(cameraId, name)
      set((state) => ({
        cameras: updateCameraList(state.cameras, updatedCamera),
      }))
      return { ok: true, message: `Preset "${name}" saved.` }
    } catch {
      return { ok: false, message: 'Failed to save preset.' }
    }
  },

  deletePtzPreset: async (cameraId, presetId) => {
    try {
      const updatedCamera = await cameraService.deletePtzPreset(cameraId, presetId)
      set((state) => ({
        cameras: updateCameraList(state.cameras, updatedCamera),
      }))
      return { ok: true, message: 'Preset deleted.' }
    } catch {
      return { ok: false, message: 'Failed to delete preset.' }
    }
  },

  clearEvents: () => {
    persistEventSnapshot([])
    set({ events: [] })
  },
}))
