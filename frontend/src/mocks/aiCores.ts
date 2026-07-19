import type { AICoreKey } from '@/types/camera'
import type { EventSeverity } from '@/types/event'

export interface AICoreDefinition {
  key: AICoreKey
  label: string
  shortLabel: string
  description: string
  defaultSeverity: EventSeverity
}

export const AI_CORE_DEFINITIONS: AICoreDefinition[] = [
  {
    key: 'fenceClimb',
    label: 'Trèo rào',
    shortLabel: 'Trèo rào',
    description: 'Phát hiện đối tượng có hành vi leo/trèo qua hàng rào, tường chắn.',
    defaultSeverity: 'high',
  },
  {
    key: 'weapon',
    label: 'Cầm vũ khí',
    shortLabel: 'Cầm vũ khí',
    description: 'Cảnh báo đối tượng mang vật thể có đặc điểm giống vũ khí.',
    defaultSeverity: 'high',
  },
  {
    key: 'crowd',
    label: 'Tụ tập đám đông',
    shortLabel: 'Tụ tập đám đông',
    description: 'Đếm mật độ tập trung người và phát hiện tụ tập bất thường.',
    defaultSeverity: 'medium',
  },
  {
    key: 'trash',
    label: 'Đổ rác trái phép',
    shortLabel: 'Đổ rác trái phép',
    description: 'Giám sát hành vi xả rác hoặc bỏ vật thể sai khu vực.',
    defaultSeverity: 'medium',
  },
  {
    key: 'parking',
    label: 'Đỗ xe trái phép',
    shortLabel: 'Đỗ xe trái phép',
    description: 'Kiểm soát xe dừng, đỗ hoặc chiếm làn sai quy định.',
    defaultSeverity: 'low',
  },
  {
    key: 'encroachment',
    label: 'Lấn chiếm vỉa hè',
    shortLabel: 'Lấn chiếm vỉa hè',
    description: 'Phát hiện hàng quán, vật cản hoặc phương tiện lấn chiếm.',
    defaultSeverity: 'medium',
  },
  {
    key: 'fight',
    label: 'Đánh nhau',
    shortLabel: 'Đánh nhau',
    description: 'Theo dõi xô xát, va chạm bất thường và phản ứng bạo lực.',
    defaultSeverity: 'high',
  },
]

export const AI_CORE_MAP = Object.fromEntries(
  AI_CORE_DEFINITIONS.map((item) => [item.key, item]),
) as Record<AICoreKey, AICoreDefinition>
