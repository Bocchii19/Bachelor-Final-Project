import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { apiConfig } from '@/services/config'
import { RegionDrawer } from '@/features/live/RegionDrawer'
import type { Camera } from '@/types/camera'

const FEATURE_LABELS: Record<string, string> = {
  Treo_rao: 'Trèo rào',
  Lan_chiem_via_he: 'Lấn chiếm via hè',
  Do_xe_trai_phep: 'Đỗ xe trái phép',
  Do_rac_trai_phep: 'Đổ rác trái phép',
}

interface AIConfigPanelProps {
  camera: Camera | null
}

export function AIConfigPanel({ camera }: AIConfigPanelProps) {
  const [schedules, setSchedules] = useState<Record<string, string>>({
    Treo_rao: '09:00 - 21:00',
    Lan_chiem_via_he: '09:00 - 21:00',
    Do_xe_trai_phep: '09:00 - 21:00',
    Do_rac_trai_phep: '09:00 - 21:00',
  })
  const [activeFeature, setActiveFeature] = useState<string | null>(null)

  // Load schedules from API
  useEffect(() => {
    fetch(`${apiConfig.baseUrl}/ai-features/schedules`)
      .then((r) => r.json())
      .then((data) => {
        const next: Record<string, string> = {}
        for (const [key, val] of Object.entries(data)) {
          next[key] = (val as { schedule: string }).schedule || '09:00 - 21:00'
        }
        setSchedules((prev) => ({ ...prev, ...next }))
      })
      .catch(() => {})
  }, [])

  const handleSaveSchedule = async (featureKey: string) => {
    const value = schedules[featureKey]
    if (!value || !/^\d{2}:\d{2}\s*-\s*\d{2}:\d{2}$/.test(value)) {
      toast.error('Sai định dạng. Dùng: HH:MM - HH:MM')
      return
    }
    try {
      const resp = await fetch(`${apiConfig.baseUrl}/ai-features/${featureKey}/schedule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schedule: value }),
      })
      const data = await resp.json()
      if (data.ok) {
        toast.success(data.message)
      } else {
        toast.error(data.detail || 'Lỗi lưu')
      }
    } catch {
      toast.error('Lỗi kết nối')
    }
  }

  if (!camera) return null

  return (
    <>
      <div className="mt-3 rounded-[28px] border-2 border-black bg-white p-6">
        <p className="text-lg font-semibold text-neutral-900">
          Cấu hình tính năng AI
        </p>

        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          {Object.entries(FEATURE_LABELS).map(([key, label]) => (
            <div
              key={key}
              className="rounded-2xl border border-neutral-200 bg-white p-5"
            >
              <p className="font-semibold text-neutral-900">{label}</p>
              <p className="mt-1 text-xs text-neutral-500">
                Thời gian áp dụng (HH:MM - HH:MM)
              </p>
              <input
                type="text"
                value={schedules[key] || '09:00 - 21:00'}
                onChange={(e) =>
                  setSchedules((prev) => ({ ...prev, [key]: e.target.value }))
                }
                placeholder="09:00 - 21:00"
                className="mt-2 w-full rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-800 outline-none focus:border-neutral-500 focus:ring-1 focus:ring-neutral-400"
              />
              <div className="mt-3 flex gap-3">
                <button
                  type="button"
                  onClick={() => setActiveFeature(key)}
                  className="inline-flex flex-1 items-center justify-center rounded-xl border border-neutral-300 bg-white px-3 py-2.5 text-sm font-medium text-neutral-700 transition hover:bg-neutral-100"
                >
                  Cấu hình
                </button>
                <button
                  type="button"
                  onClick={() => handleSaveSchedule(key)}
                  className="inline-flex flex-1 items-center justify-center rounded-xl border border-neutral-300 bg-white px-3 py-2.5 text-sm font-medium text-neutral-700 transition hover:bg-neutral-100"
                >
                  Lưu
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Region Drawer Modal — time + polygon */}
      {activeFeature && (
        <RegionDrawer
          cameraId={camera.id}
          featureKey={activeFeature}
          featureLabel={FEATURE_LABELS[activeFeature] || activeFeature}
          schedule={schedules[activeFeature] || '09:00 - 21:00'}
          onScheduleChange={(val) =>
            setSchedules((prev) => ({ ...prev, [activeFeature]: val }))
          }
          open={true}
          onClose={() => setActiveFeature(null)}
        />
      )}
    </>
  )
}
