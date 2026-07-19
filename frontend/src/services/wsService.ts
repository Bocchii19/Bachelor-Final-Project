/**
 * WebSocket service for real-time event push from backend.
 *
 * Connects to ws://backend/ws/events and dispatches events to the Zustand store.
 * Uses exponential backoff to avoid hammering on reconnect.
 */

import { apiConfig } from '@/services/config'
import { useAppStore } from '@/store/appStore'
import type { EventItem } from '@/types/event'

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let pingTimer: ReturnType<typeof setInterval> | null = null
let reconnectAttempts = 0
const MAX_RECONNECT_ATTEMPTS = 10
const BASE_RECONNECT_MS = 5000
const PING_INTERVAL_MS = 30000

function getWsUrl(): string {
  const base = apiConfig.baseUrl.replace(/\/api\/?$/, '')
  const url = new URL(base)
  return `ws://${url.host}/ws/events`
}

function handleMessage(event: MessageEvent) {
  if (event.data === 'pong') return

  try {
    const data = JSON.parse(event.data) as EventItem
    if (data.id && data.cameraId && data.core) {
      useAppStore.getState().prependEvent({
        ...data,
        isNew: true,
      })
    }
  } catch {
    // Ignore non-JSON messages
  }
}

function startPing() {
  stopPing()
  pingTimer = setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send('ping')
    }
  }, PING_INTERVAL_MS)
}

function stopPing() {
  if (pingTimer) {
    clearInterval(pingTimer)
    pingTimer = null
  }
}

export function connectEventWs() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) {
    return
  }

  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    console.log('[WS] Max reconnect attempts reached, stopping')
    return
  }

  const url = getWsUrl()

  try {
    ws = new WebSocket(url)
  } catch {
    return
  }

  ws.onopen = () => {
    console.log('[WS] Connected')
    reconnectAttempts = 0
    startPing()
  }

  ws.onmessage = handleMessage

  ws.onclose = () => {
    stopPing()
    reconnectAttempts++
    const delay = Math.min(BASE_RECONNECT_MS * reconnectAttempts, 30000)
    scheduleReconnect(delay)
  }

  ws.onerror = () => {
    // onclose fires after onerror
  }
}

function scheduleReconnect(delay: number = BASE_RECONNECT_MS) {
  if (reconnectTimer) return
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connectEventWs()
  }, delay)
}

export function disconnectEventWs() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  stopPing()
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
  reconnectAttempts = 0
}

export function isWsConnected(): boolean {
  return ws?.readyState === WebSocket.OPEN
}
