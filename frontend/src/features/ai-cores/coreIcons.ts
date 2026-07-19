import type { LucideIcon } from 'lucide-react'
import {
  CarFront,
  Construction,
  Crosshair,
  Fence,
  ShieldAlert,
  Trash2,
  Users,
} from 'lucide-react'

import type { AICoreKey } from '@/types/camera'

export const AI_CORE_ICONS: Record<AICoreKey, LucideIcon> = {
  fight: ShieldAlert,
  weapon: Crosshair,
  crowd: Users,
  trash: Trash2,
  parking: CarFront,
  encroachment: Construction,
  fenceClimb: Fence,
}
