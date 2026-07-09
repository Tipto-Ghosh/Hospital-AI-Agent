import { useCallback, useEffect, useRef, useState } from "react";
import { CONNECTION_STATUS, WS_RECONNECT_DELAYS, WS_URL } from '../utils/constants'


function makeId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useWebSocket(sessionId) {
  const [messages, setMessages] = useState([])
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingAgent, setStreamingAgent] = useState('')
  const [connectionStatus, setConnectionStatus] = useState(CONNECTION_STATUS.CONNECTING)
  const [isStreaming, setIsStreaming] = useState(false)

  const wsRef = useRef(null)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef(null)
  const deliberateCloseRef = useRef(false)
  const streamingContentRef = useRef('')
  const streamingAgentRef = useRef('')

  const clearMessages = useCallback(() => {
    setMessages([])
    setStreamingContent('')
    streamingContentRef.current = ''
    setStreamingAgent('')
    streamingAgentRef.current = ''
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) return

    deliberateCloseRef.current = false
    setConnectionStatus((prev) =>
      prev === CONNECTION_STATUS.CONNECTED ? CONNECTION_STATUS.RECONNECTING : CONNECTION_STATUS.CONNECTING
    )

    const ws = new WebSocket(`${WS_URL}/api/v1/chat/ws/${sessionId}`)
    wsRef.current = ws

    ws.onopen = () => {
      reconnectAttemptRef.current = 0
      setConnectionStatus(CONNECTION_STATUS.CONNECTED)
    }

    ws.onmessage = (event) => {
      let frame
      try {
        frame = JSON.parse(event.data)
      } catch {
        return
      }

      if (frame.type === 'chunk') {
        streamingContentRef.current += frame.content ?? ''
        streamingAgentRef.current = frame.agent ?? streamingAgentRef.current
        setStreamingContent(streamingContentRef.current)
        setStreamingAgent(streamingAgentRef.current)
        setIsStreaming(true)
        return
      }

      if (frame.type === 'done') {
        const finalContent = streamingContentRef.current
        setMessages((prev) => [
          ...prev,
          {
            id: makeId(),
            role: 'ai',
            content: finalContent,
            agent: frame.agent ?? streamingAgentRef.current,
            intent: frame.metadata?.intent ?? '',
            is_emergency: frame.metadata?.is_emergency ?? false,
            timestamp: new Date(),
          },
        ])
        streamingContentRef.current = ''
        streamingAgentRef.current = ''
        setStreamingContent('')
        setStreamingAgent('')
        setIsStreaming(false)
        return
      }

      if (frame.type === 'error') {
        setMessages((prev) => [
          ...prev,
          {
            id: makeId(),
            role: 'error',
            content: frame.message ?? 'Something went wrong. Please try again.',
            agent: '',
            intent: '',
            is_emergency: false,
            timestamp: new Date(),
          },
        ])
        streamingContentRef.current = ''
        streamingAgentRef.current = ''
        setStreamingContent('')
        setStreamingAgent('')
        setIsStreaming(false)
      }
    }

    ws.onclose = () => {
      if (deliberateCloseRef.current) return

      const delays = WS_RECONNECT_DELAYS
      const attempt = reconnectAttemptRef.current

      if (attempt >= delays.length) {
        setConnectionStatus(CONNECTION_STATUS.DISCONNECTED)
        return
      }

      setConnectionStatus(CONNECTION_STATUS.RECONNECTING)
      const delay = delays[attempt]
      reconnectAttemptRef.current = attempt + 1
      reconnectTimerRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [sessionId])

  useEffect(() => {
    if (!sessionId) return undefined

    connect()

    return () => {
      deliberateCloseRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  const sendMessage = useCallback(
    (text) => {
      const trimmed = text.trim()
      if (!trimmed || !sessionId) return

      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: 'patient',
          content: trimmed,
          agent: '',
          intent: '',
          is_emergency: false,
          timestamp: new Date(),
        },
      ])

      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'message', session_id: sessionId, text: trimmed }))
        setIsStreaming(true)
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: makeId(),
            role: 'error',
            content: 'Connection lost. Please refresh the page.',
            agent: '',
            intent: '',
            is_emergency: false,
            timestamp: new Date(),
          },
        ])
      }
    },
    [sessionId]
  )

  return {
    messages,
    streamingContent,
    streamingAgent,
    sendMessage,
    connectionStatus,
    isStreaming,
    clearMessages,
  }
}