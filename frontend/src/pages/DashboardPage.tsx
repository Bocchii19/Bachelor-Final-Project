import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { BrandBar } from '@/components/layout/BrandBar'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { EmptyState } from '@/components/ui/EmptyState'
import * as cameraService from '@/services/cameraService'
import { connectEventWs, disconnectEventWs } from '@/services/wsService'
import { CameraModal } from '@/features/cameras/CameraModal'
import { CameraTabs } from '@/features/cameras/CameraTabs'
import { EventPanel } from '@/features/events/EventPanel'
import { ControlPanel } from '@/features/live/ControlPanel'
import { LiveStreamPanel } from '@/features/live/LiveStreamPanel'
import { AIConfigPanel } from '@/features/live/AIConfigPanel'
import { useDashboardBootstrap } from '@/hooks/useDashboardBootstrap'
import { useAppStore } from '@/store/appStore'
import type { CameraFormValues, HomePositionState } from '@/types/camera'
import { Camera } from 'lucide-react'

type CameraModalState =
  | { mode: 'add' }
  | { mode: 'edit'; cameraId: string }
  | null

const DEFAULT_HOME_STATE: HomePositionState = {
  home_set: false,
  pan: 0,
  tilt: 0,
  zoom: 0,
}

export function DashboardPage() {
  useDashboardBootstrap()

  const cameras = useAppStore((state) => state.cameras)
  const events = useAppStore((state) => state.events)
  const selectedCameraId = useAppStore((state) => state.selectedCameraId)
  const activeStream = useAppStore((state) => state.activeStream)
  const eventFilters = useAppStore((state) => state.eventFilters)
  const pendingAction = useAppStore((state) => state.pendingAction)
  const isBootstrapped = useAppStore((state) => state.isBootstrapped)
  const setSelectedCamera = useAppStore((state) => state.setSelectedCamera)
  const setEventFilters = useAppStore((state) => state.setEventFilters)
  const toggleCoreSelection = useAppStore((state) => state.toggleCoreSelection)
  const showSelectedCamera = useAppStore((state) => state.showSelectedCamera)
  const stopSelectedCamera = useAppStore((state) => state.stopSelectedCamera)
  const runSelectedCameraCores = useAppStore((state) => state.runSelectedCameraCores)
  const stopSelectedCameraCores = useAppStore((state) => state.stopSelectedCameraCores)
  const addCamera = useAppStore((state) => state.addCamera)
  const updateCamera = useAppStore((state) => state.updateCamera)
  const deleteCamera = useAppStore((state) => state.deleteCamera)
  const clearEvents = useAppStore((state) => state.clearEvents)

  const [cameraModalState, setCameraModalState] = useState<CameraModalState>(null)
  const [deleteCameraId, setDeleteCameraId] = useState<string | null>(null)
  const [homeStates, setHomeStates] = useState<Record<string, HomePositionState>>({})

  const filteredEvents = events.filter((event) => {
    const cameraMatches = selectedCameraId !== null && event.cameraId === selectedCameraId
    const coreMatches = eventFilters.core === 'all' || event.core === eventFilters.core
    return cameraMatches && coreMatches
  })

  const eventCounts = events.reduce<Record<string, number>>((accumulator, event) => {
    accumulator[event.cameraId] = (accumulator[event.cameraId] ?? 0) + 1
    return accumulator
  }, {})

  const selectedCamera = cameras.find((camera) => camera.id === selectedCameraId) ?? null
  const editingCamera =
    cameraModalState?.mode === 'edit'
      ? cameras.find((camera) => camera.id === cameraModalState.cameraId) ?? null
      : null
  const deleteTarget = cameras.find((camera) => camera.id === deleteCameraId) ?? null
  const selectedHomeState =
    (selectedCamera && homeStates[selectedCamera.id]) || DEFAULT_HOME_STATE

  const handleAsyncResult = async (operation: Promise<{ ok: boolean; message: string }>) => {
    const result = await operation
    if (result.ok) {
      toast.success(result.message)
      return true
    }

    toast.error(result.message)
    return false
  }

  const handleCameraSubmit = async (values: CameraFormValues) => {
    if (!cameraModalState) {
      return
    }

    const result =
      cameraModalState.mode === 'add'
        ? await addCamera(values)
        : await updateCamera(cameraModalState.cameraId, values)

    if (result.ok) {
      toast.success(result.message)
      setCameraModalState(null)
      return
    }

    toast.error(result.message)
  }

  const handleDelete = async () => {
    if (!deleteCameraId) {
      return
    }

    const result = await deleteCamera(deleteCameraId)
    if (result.ok) {
      toast.success(result.message)
      setDeleteCameraId(null)
      return
    }

    toast.error(result.message)
  }

  const handleClearEvents = () => {
    clearEvents()
    toast.success('Event log cleared.')
  }

  const refreshHomeState = async (cameraId: string, rtspUrl: string) => {
    const status = await cameraService.ptzGetHomeStatus(cameraId, rtspUrl)
    setHomeStates((prev) => ({ ...prev, [cameraId]: status }))
  }

  // ── WebSocket for real-time events ──
  useEffect(() => {
    connectEventWs()
    return () => {
      disconnectEventWs()
    }
  }, [])

  useEffect(() => {
    if (!selectedCamera || selectedCamera.type !== 'ptz') {
      return
    }
    void refreshHomeState(selectedCamera.id, selectedCamera.rtspUrl)
    const intervalId = window.setInterval(() => {
      void refreshHomeState(selectedCamera.id, selectedCamera.rtspUrl)
    }, 1000)
    return () => {
      window.clearInterval(intervalId)
    }
  }, [selectedCamera?.id, selectedCamera?.rtspUrl, selectedCamera?.type])

  return (
    <>
      <main className="mx-auto flex min-h-screen w-full max-w-[1920px] flex-col gap-3 px-4 py-4 md:px-5">
        <BrandBar />

        {isBootstrapped && cameras.length === 0 ? (
          <div className="border-2 border-black bg-white p-6">
            <EmptyState
              icon={Camera}
              title="No camera has been configured yet"
              description="Use Add Camera to create the first mock stream source. The dashboard will persist it in localStorage so refresh does not lose your setup."
              action={
                <button
                  type="button"
                  onClick={() => setCameraModalState({ mode: 'add' })}
                  className="border-2 border-black bg-white px-4 py-2.5 text-sm font-semibold text-black transition hover:bg-neutral-100"
                >
                  Add first camera
                </button>
              }
            />
          </div>
        ) : (
          <>
            <CameraTabs
              cameras={cameras}
              selectedCameraId={selectedCameraId}
              eventCounts={eventCounts}
              onSelectCamera={setSelectedCamera}
              onAddCamera={() => setCameraModalState({ mode: 'add' })}
            />

            <div className="grid gap-3 xl:grid-cols-[220px_minmax(0,1fr)_240px]">
              <EventPanel
                events={filteredEvents}
                filters={eventFilters}
                onChangeFilters={setEventFilters}
                onClearEvents={handleClearEvents}
              />
              <div className="flex flex-col">
                <LiveStreamPanel camera={selectedCamera} activeStream={activeStream} />
                <AIConfigPanel camera={selectedCamera} />
              </div>
              <ControlPanel
                camera={selectedCamera}
                pendingAction={pendingAction}
                onShow={() => {
                  void handleAsyncResult(showSelectedCamera())
                }}
                onStop={() => {
                  void handleAsyncResult(stopSelectedCamera())
                }}
                onRun={() => {
                  void handleAsyncResult(runSelectedCameraCores())
                }}
                onStopRun={() => {
                  void handleAsyncResult(stopSelectedCameraCores())
                }}
                onEdit={() =>
                  selectedCamera && setCameraModalState({ mode: 'edit', cameraId: selectedCamera.id })
                }
                onDelete={() => selectedCamera && setDeleteCameraId(selectedCamera.id)}
                onToggleCore={(core) => {
                  void toggleCoreSelection(core)
                }}
                onPtzMove={(direction) => {
                  if (!selectedCamera) return
                  void (async () => {
                    const result = await cameraService.ptzMove(
                      selectedCamera.id,
                      selectedCamera.rtspUrl,
                      direction,
                    )
                    if (result.homeState) {
                      setHomeStates((prev) => ({ ...prev, [selectedCamera.id]: result.homeState }))
                    }
                    if (result.ok) {
                      toast.success(result.message)
                    } else {
                      toast.error(result.message)
                    }
                  })()
                }}
                onZoom={(action) => {
                  if (!selectedCamera) return
                  void (async () => {
                    const result = await cameraService.ptzZoom(
                      selectedCamera.id,
                      selectedCamera.rtspUrl,
                      action,
                    )
                    if (result.homeState) {
                      setHomeStates((prev) => ({ ...prev, [selectedCamera.id]: result.homeState }))
                    }
                    if (result.ok) {
                      toast.success(result.message)
                    } else {
                      toast.error(result.message)
                    }
                  })()
                }}
                homePositionState={selectedHomeState}
                onSetHomePosition={() => {
                  if (!selectedCamera) return
                  const password = window.prompt('Nhập mật khẩu để SET HOME:')
                  if (!password) {
                    toast.error('Hủy SET HOME: chưa nhập mật khẩu.')
                    return
                  }
                  void (async () => {
                    const result = await cameraService.ptzSetHome(
                      selectedCamera.id,
                      selectedCamera.rtspUrl,
                      password,
                    )
                    if (result.homeState) {
                      setHomeStates((prev) => ({ ...prev, [selectedCamera.id]: result.homeState }))
                    }
                    if (result.ok) {
                      toast.success(result.message)
                    } else {
                      toast.error(result.message)
                    }
                  })()
                }}
                onGotoHomePosition={() => {
                  if (!selectedCamera) return
                  void (async () => {
                    const result = await cameraService.ptzGotoHome(
                      selectedCamera.id,
                      selectedCamera.rtspUrl,
                    )
                    if (result.homeState) {
                      setHomeStates((prev) => ({ ...prev, [selectedCamera.id]: result.homeState }))
                    }
                    if (result.ok) {
                      toast.success(result.message)
                    } else {
                      toast.error(result.message)
                    }
                  })()
                }}
              />
            </div>
          </>
        )}
      </main>

      <CameraModal
        key={
          cameraModalState
            ? cameraModalState.mode === 'edit'
              ? `edit-${cameraModalState.cameraId}`
              : 'add'
            : 'closed'
        }
        open={cameraModalState !== null}
        mode={cameraModalState?.mode ?? 'add'}
        cameras={cameras}
        editingCamera={editingCamera}
        isSubmitting={pendingAction === 'save'}
        onClose={() => setCameraModalState(null)}
        onSubmit={handleCameraSubmit}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete camera"
        description={
          deleteTarget
            ? `Remove ${deleteTarget.name} from the dashboard? This will also delete its event history from local storage.`
            : ''
        }
        confirmLabel="Delete camera"
        isLoading={pendingAction === 'delete'}
        onClose={() => setDeleteCameraId(null)}
        onConfirm={() => {
          void handleDelete()
        }}
      />
    </>
  )
}
