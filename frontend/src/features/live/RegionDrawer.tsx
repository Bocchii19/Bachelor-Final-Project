import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { apiConfig } from '@/services/config'
import { Undo2, Trash2, Save, X } from 'lucide-react'

interface Point {
  x: number
  y: number
}

interface RegionDrawerProps {
  cameraId: string
  featureKey: string
  featureLabel: string
  schedule: string
  onScheduleChange: (val: string) => void
  open: boolean
  onClose: () => void
}

export function RegionDrawer({
  cameraId,
  featureKey,
  featureLabel,
  schedule,
  onScheduleChange,
  open,
  onClose,
}: RegionDrawerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [points, setPoints] = useState<Point[]>([])
  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null)
  const [imgNatural, setImgNatural] = useState({ w: 1920, h: 1080 })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const imgRef = useRef<HTMLImageElement | null>(null)

  // ── Load snapshot + existing region2 ──
  useEffect(() => {
    if (!open) return
    setLoading(true)

    // Fetch snapshot
    const url = `${apiConfig.baseUrl}/polygon/${cameraId}/snapshot?ts=${Date.now()}`
    setSnapshotUrl(url)

    // Only load existing polygon for Treo_rao
    if (featureKey === 'Treo_rao') {
      fetch(`${apiConfig.baseUrl}/polygon/${cameraId}/region2`)
        .then((r) => r.json())
        .then((data) => {
          if (data.points && Array.isArray(data.points)) {
            setPoints(data.points.map((p: number[]) => ({ x: p[0], y: p[1] })))
          }
          if (data.resolution) {
            setImgNatural({ w: data.resolution.width, h: data.resolution.height })
          }
        })
        .catch(() => {
          setPoints([])
        })
        .finally(() => setLoading(false))
    } else {
      setPoints([])
      setLoading(false)
    }
  }, [open, cameraId, featureKey])

  // ── Draw canvas ──
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current
    const img = imgRef.current
    if (!canvas || !img || !img.complete) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = canvas.offsetWidth
    canvas.height = canvas.offsetHeight

    // Draw image scaled to canvas
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)

    if (points.length === 0) return

    const scaleX = canvas.width / imgNatural.w
    const scaleY = canvas.height / imgNatural.h

    // Draw filled polygon
    if (points.length >= 3) {
      ctx.beginPath()
      ctx.moveTo(points[0].x * scaleX, points[0].y * scaleY)
      for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x * scaleX, points[i].y * scaleY)
      }
      ctx.closePath()
      ctx.fillStyle = 'rgba(0, 200, 80, 0.2)'
      ctx.fill()
    }

    // Draw lines
    ctx.beginPath()
    ctx.moveTo(points[0].x * scaleX, points[0].y * scaleY)
    for (let i = 1; i < points.length; i++) {
      ctx.lineTo(points[i].x * scaleX, points[i].y * scaleY)
    }
    if (points.length >= 3) ctx.closePath()
    ctx.strokeStyle = '#00c850'
    ctx.lineWidth = 2
    ctx.stroke()

    // Draw points
    points.forEach((p, idx) => {
      const cx = p.x * scaleX
      const cy = p.y * scaleY
      ctx.beginPath()
      ctx.arc(cx, cy, 5, 0, Math.PI * 2)
      ctx.fillStyle = idx === points.length - 1 ? '#ff6b00' : '#00c850'
      ctx.fill()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 1.5
      ctx.stroke()

      // Point number
      ctx.fillStyle = '#fff'
      ctx.font = 'bold 11px Inter, sans-serif'
      ctx.fillText(`${idx + 1}`, cx + 8, cy - 4)
    })
  }, [points, imgNatural])

  useEffect(() => {
    drawCanvas()
  }, [drawCanvas])

  // ── Click to add point ──
  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const clickX = e.clientX - rect.left
    const clickY = e.clientY - rect.top

    // Convert canvas coords → image coords
    const scaleX = imgNatural.w / canvas.width
    const scaleY = imgNatural.h / canvas.height
    const imgX = Math.round(clickX * scaleX)
    const imgY = Math.round(clickY * scaleY)

    setPoints((prev) => [...prev, { x: imgX, y: imgY }])
  }

  // ── Right-click to undo ──
  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault()
    setPoints((prev) => prev.slice(0, -1))
  }

  // ── Save all (schedule + polygon) ──
  const handleSave = async () => {
    setSaving(true)
    try {
      // 1. Save schedule
      if (schedule && /^\d{2}:\d{2}\s*-\s*\d{2}:\d{2}$/.test(schedule)) {
        await fetch(`${apiConfig.baseUrl}/ai-features/${featureKey}/schedule`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ schedule }),
        })
      }

      // 2. Save polygon (only for Treo_rao with enough points)
      if (featureKey === 'Treo_rao' && points.length >= 3) {
        const resp = await fetch(`${apiConfig.baseUrl}/polygon/${cameraId}/region2`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            points: points.map((p) => [p.x, p.y]),
            // Gửi resolution thực tế của ảnh để backend scale polygon đúng
            resolution: { width: imgNatural.w, height: imgNatural.h },
          }),
        })
        const data = await resp.json()
        if (!data.ok) {
          toast.error(data.detail || 'Lỗi lưu polygon')
          setSaving(false)
          return
        }
      }

      toast.success(`${featureLabel}: Đã lưu cấu hình`)
      onClose()
    } catch {
      toast.error('Lỗi kết nối server')
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  const showPolygon = featureKey === 'Treo_rao'

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative flex max-h-[90vh] w-[90vw] max-w-[1200px] flex-col overflow-hidden rounded-3xl border border-neutral-200 bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-neutral-900">
              Cấu hình — <span className="text-green-600">{featureLabel}</span>
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-neutral-200 bg-white text-neutral-600 transition hover:bg-neutral-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Schedule input */}
        <div className="border-b border-neutral-100 px-6 py-4">
          <label className="text-sm font-medium text-neutral-700">
            Thời gian áp dụng (HH:MM - HH:MM)
          </label>
          <input
            type="text"
            value={schedule}
            onChange={(e) => onScheduleChange(e.target.value)}
            placeholder="09:00 - 21:00"
            className="mt-2 w-full rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-800 outline-none focus:border-neutral-500 focus:ring-1 focus:ring-neutral-400"
          />
        </div>

        {/* Canvas — only for Treo_rao */}
        {showPolygon && (
          <div className="relative flex-1 bg-neutral-900 p-4">
            {loading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center">
                <p className="text-white">Đang tải snapshot...</p>
              </div>
            )}
            {/* Hidden image for loading */}
            {snapshotUrl && (
              <img
                ref={imgRef}
                src={snapshotUrl}
                alt=""
                className="hidden"
                crossOrigin="anonymous"
                onLoad={(e) => {
                  const img = e.currentTarget
                  setImgNatural({ w: img.naturalWidth, h: img.naturalHeight })
                  setLoading(false)
                  drawCanvas()
                }}
              />
            )}
            <canvas
              ref={canvasRef}
              onClick={handleCanvasClick}
              onContextMenu={handleContextMenu}
              className="h-full w-full cursor-crosshair rounded-xl"
              style={{ aspectRatio: `${imgNatural.w}/${imgNatural.h}` }}
            />
            <p className="mt-2 text-center text-xs text-neutral-400">
              Click trái: thêm điểm · Click phải: xóa điểm cuối · {points.length} điểm
            </p>
          </div>
        )}

        {/* Footer actions */}
        <div className="flex items-center justify-between border-t border-neutral-200 px-6 py-4">
          <div className="flex gap-2">
            {showPolygon && (
              <>
                <button
                  type="button"
                  onClick={() => setPoints((prev) => prev.slice(0, -1))}
                  disabled={points.length === 0}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-neutral-300 bg-white px-4 py-2.5 text-sm font-medium text-neutral-700 transition hover:bg-neutral-100 disabled:opacity-40"
                >
                  <Undo2 className="h-4 w-4" /> Undo
                </button>
                <button
                  type="button"
                  onClick={() => setPoints([])}
                  disabled={points.length === 0}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-white px-4 py-2.5 text-sm font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" /> Xóa tất cả
                </button>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-xl border border-green-600 bg-green-600 px-6 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:bg-green-700 disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {saving ? 'Đang lưu...' : 'Lưu'}
          </button>
        </div>
      </div>
    </div>
  )
}
