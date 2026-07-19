import type { EventItem } from '@/types/event'
import { readStorage, writeStorage } from '@/utils/storage'

const EVENT_STORAGE_KEY = 'surveillance-system:events'
const MAX_EVENTS = 120

function delay(duration = 140) {
  return new Promise((resolve) => window.setTimeout(resolve, duration))
}

function readEvents(): EventItem[] {
  return readStorage<EventItem[]>(EVENT_STORAGE_KEY, [])
}

export async function getEvents() {
  await delay()
  return readEvents().slice(0, MAX_EVENTS)
}

export function persistEvents(events: EventItem[]) {
  writeStorage(EVENT_STORAGE_KEY, events.slice(0, MAX_EVENTS))
}
