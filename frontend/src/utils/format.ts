const timestampFormatter = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

const timeFormatter = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

export function formatTimestamp(value: string) {
  return timestampFormatter.format(new Date(value))
}

export function formatTimeOnly(value: string) {
  return timeFormatter.format(new Date(value))
}

export function formatRelativeTime(value: string) {
  const diffSeconds = Math.round((Date.now() - new Date(value).getTime()) / 1000)

  if (diffSeconds < 10) {
    return 'just now'
  }

  if (diffSeconds < 60) {
    return `${diffSeconds}s ago`
  }

  const diffMinutes = Math.round(diffSeconds / 60)
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`
  }

  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) {
    return `${diffHours}h ago`
  }

  const diffDays = Math.round(diffHours / 24)
  return `${diffDays}d ago`
}

export function trimText(value: string) {
  return value.trim().replace(/\s+/g, ' ')
}
