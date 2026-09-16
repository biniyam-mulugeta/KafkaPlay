/**
 * Live tail over WebSocket.
 *
 * Keeps a bounded buffer: a live tail shows current traffic, so old messages
 * are dropped rather than accumulated until the tab runs out of memory.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import type { KafkaMessage } from '@/lib/api'

const MAX_BUFFERED = 500

interface TailState {
  active: boolean
  paused: boolean
  messages: KafkaMessage[]
  error: string | null
  start: () => void
  stop: () => void
  togglePause: () => void
}

export function useTail(
  cluster: string | null,
  topic: string,
  filter: string,
): TailState {
  const [active, setActive] = useState(false)
  const [paused, setPaused] = useState(false)
  const [messages, setMessages] = useState<KafkaMessage[]>([])
  const [error, setError] = useState<string | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const pausedRef = useRef(false)

  const stop = useCallback(() => {
    const socket = socketRef.current
    if (socket) {
      try {
        if (socket.readyState === WebSocket.OPEN) socket.send('stop')
        socket.close()
      } catch {
        // Already closing; nothing to do.
      }
    }
    socketRef.current = null
    setActive(false)
    setPaused(false)
    pausedRef.current = false
  }, [])

  const start = useCallback(() => {
    if (!cluster || !topic) return
    stop()
    setMessages([])
    setError(null)

    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const query = filter.trim() ? `?filter=${encodeURIComponent(filter.trim())}` : ''
    const url = `${scheme}://${window.location.host}/ws/tail/${encodeURIComponent(
      cluster,
    )}/${encodeURIComponent(topic)}${query}`

    const socket = new WebSocket(url)
    socketRef.current = socket
    setActive(true)

    socket.onmessage = (event) => {
      if (pausedRef.current) return
      try {
        const payload = JSON.parse(event.data as string)
        if (payload._error) {
          setError(String(payload._error))
          return
        }
        setMessages((current) => {
          // Newest first, bounded.
          const next = [payload as KafkaMessage, ...current]
          return next.length > MAX_BUFFERED ? next.slice(0, MAX_BUFFERED) : next
        })
      } catch {
        // A malformed frame is not worth tearing the stream down for.
      }
    }

    socket.onerror = () => setError('the live tail connection failed')
    socket.onclose = () => {
      socketRef.current = null
      setActive(false)
    }
  }, [cluster, topic, filter, stop])

  const togglePause = useCallback(() => {
    setPaused((value) => {
      pausedRef.current = !value
      return !value
    })
  }, [])

  // Always close the socket when the page unmounts, so a closed tab never
  // leaves a consumer running against the broker.
  useEffect(() => stop, [stop])

  return { active, paused, messages, error, start, stop, togglePause }
}
