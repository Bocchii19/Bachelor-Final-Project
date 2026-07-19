import { useState, type FormEvent } from 'react'

import { Modal } from '@/components/ui/Modal'
import type { Camera, CameraFormValues } from '@/types/camera'
import { trimText } from '@/utils/format'

interface CameraModalProps {
  open: boolean
  mode: 'add' | 'edit'
  cameras: Camera[]
  editingCamera?: Camera | null
  isSubmitting?: boolean
  onClose: () => void
  onSubmit: (values: CameraFormValues) => Promise<void>
}

type FormErrors = Partial<Record<keyof CameraFormValues, string>>

const defaultValues: CameraFormValues = {
  name: '',
  rtspUrl: 'rtsp://',
  location: '',
  description: '',
}

function validate(values: CameraFormValues, cameras: Camera[], editingCameraId?: string): FormErrors {
  const errors: FormErrors = {}
  const normalizedName = trimText(values.name)
  const normalizedRtsp = trimText(values.rtspUrl)
  const normalizedLocation = trimText(values.location)

  if (!normalizedName) {
    errors.name = 'Camera name is required.'
  }

  const isDuplicated = cameras.some(
    (camera) =>
      camera.id !== editingCameraId &&
      camera.name.trim().toLowerCase() === normalizedName.toLowerCase(),
  )
  if (normalizedName && isDuplicated) {
    errors.name = 'Camera name must be unique.'
  }

  if (!normalizedRtsp) {
    errors.rtspUrl = 'RTSP URL is required.'
  } else if (!/^rtsps?:\/\//i.test(normalizedRtsp)) {
    errors.rtspUrl = 'RTSP URL must start with rtsp:// or rtsps://'
  }

  if (!normalizedLocation) {
    errors.location = 'Location is required.'
  }

  if (values.description.trim().length > 180) {
    errors.description = 'Description should be under 180 characters.'
  }

  return errors
}

export function CameraModal({
  open,
  mode,
  cameras,
  editingCamera,
  isSubmitting = false,
  onClose,
  onSubmit,
}: CameraModalProps) {
  const initialValues = editingCamera
    ? {
        name: editingCamera.name,
        rtspUrl: editingCamera.rtspUrl,
        location: editingCamera.location,
        description: editingCamera.description,
      }
    : defaultValues

  const [values, setValues] = useState<CameraFormValues>(initialValues)
  const [errors, setErrors] = useState<FormErrors>({})

  const handleChange = <Field extends keyof CameraFormValues>(
    field: Field,
    value: CameraFormValues[Field],
  ) => {
    setValues((currentValues) => ({
      ...currentValues,
      [field]: value,
    }))

    if (errors[field]) {
      setErrors((currentErrors) => ({
        ...currentErrors,
        [field]: undefined,
      }))
    }
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const nextErrors = validate(values, cameras, editingCamera?.id)
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors)
      return
    }

    await onSubmit({
      name: trimText(values.name),
      rtspUrl: trimText(values.rtspUrl),
      location: trimText(values.location),
      description: trimText(values.description),
    })
  }

  return (
    <Modal
      open={open}
      title={mode === 'add' ? 'Add Camera' : 'Edit Camera'}
      description="Cac truong nay dang dung mock persistence, nhung contract da san sang de noi backend that."
      onClose={onClose}
      footer={
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-2xl border border-neutral-300 bg-white px-4 py-2.5 text-sm font-semibold text-neutral-800 transition hover:bg-neutral-100"
          >
            Cancel
          </button>
          <button
            type="submit"
            form="camera-form"
            disabled={isSubmitting}
            className="rounded-2xl border border-black bg-black px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? 'Saving...' : mode === 'add' ? 'Create Camera' : 'Save Changes'}
          </button>
        </div>
      }
    >
      <form id="camera-form" onSubmit={handleSubmit} className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <label className="text-sm font-medium text-neutral-900">Camera name</label>
          <input
            value={values.name}
            onChange={(event) => handleChange('name', event.target.value)}
            placeholder="Bullet 5"
            className="h-12 w-full rounded-2xl border border-neutral-300 bg-neutral-50 px-4 text-sm text-neutral-900 outline-none transition placeholder:text-neutral-500 focus:border-neutral-500 focus:bg-white"
          />
          {errors.name ? <p className="text-xs text-neutral-800">{errors.name}</p> : null}
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-neutral-900">Location</label>
          <input
            value={values.location}
            onChange={(event) => handleChange('location', event.target.value)}
            placeholder="North Gate"
            className="h-12 w-full rounded-2xl border border-neutral-300 bg-neutral-50 px-4 text-sm text-neutral-900 outline-none transition placeholder:text-neutral-500 focus:border-neutral-500 focus:bg-white"
          />
          {errors.location ? <p className="text-xs text-neutral-800">{errors.location}</p> : null}
        </div>

        <div className="space-y-2 md:col-span-2">
          <label className="text-sm font-medium text-neutral-900">RTSP URL</label>
          <input
            value={values.rtspUrl}
            onChange={(event) => handleChange('rtspUrl', event.target.value)}
            placeholder="rtsp://demo.local/new-camera"
            className="h-12 w-full rounded-2xl border border-neutral-300 bg-neutral-50 px-4 text-sm font-mono text-neutral-900 outline-none transition placeholder:text-neutral-500 focus:border-neutral-500 focus:bg-white"
          />
          {errors.rtspUrl ? <p className="text-xs text-neutral-800">{errors.rtspUrl}</p> : null}
        </div>

        <div className="space-y-2 md:col-span-2">
          <label className="text-sm font-medium text-neutral-900">Description</label>
          <textarea
            value={values.description}
            onChange={(event) => handleChange('description', event.target.value)}
            rows={4}
            placeholder="Short operational note for operators."
            className="w-full rounded-2xl border border-neutral-300 bg-neutral-50 px-4 py-3 text-sm text-neutral-900 outline-none transition placeholder:text-neutral-500 focus:border-neutral-500 focus:bg-white"
          />
          <div className="flex items-center justify-between">
            {errors.description ? (
              <p className="text-xs text-neutral-800">{errors.description}</p>
            ) : (
              <p className="text-xs text-neutral-500">Optional note used in operator panel.</p>
            )}
            <p className="text-xs text-neutral-500">{values.description.length}/180</p>
          </div>
        </div>
      </form>
    </Modal>
  )
}
