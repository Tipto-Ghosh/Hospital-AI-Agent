import { useCallback, useEffect, useState } from 'react'
import { createSession, getHistory } from '../api/session'
import { SESSION_STORAGE_KEY } from '../utils/constants'

export function useSession() {
  const [sessionId, setSessionId] = useState(null)
  const [priorMessages, setPriorMessages] = useState([])
  const [isReady, setIsReady] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function init() {
      const stored = localStorage.getItem(SESSION_STORAGE_KEY)

      if (stored) {
        try {
          const history = await getHistory(stored)
          if (cancelled) return
          setSessionId(stored)
          setPriorMessages(history.messages ?? [])
          setIsReady(true)
          return
        } catch {
          localStorage.removeItem(SESSION_STORAGE_KEY)
        }
      }

      try {
        const { session_id } = await createSession()
        if (cancelled) return
        localStorage.setItem(SESSION_STORAGE_KEY, session_id)
        setSessionId(session_id)
        setPriorMessages([])
        setIsReady(true)
      } catch {
        if (!cancelled) {
          setError('Could not connect to the hospital system. Please refresh the page.')
        }
      }
    }

    init()

    return () => {
      cancelled = true
    }
  }, [])

  const resetSession = useCallback(async () => {
    localStorage.removeItem(SESSION_STORAGE_KEY)
    setError(null)
    try {
      const { session_id } = await createSession()
      localStorage.setItem(SESSION_STORAGE_KEY, session_id)
      setSessionId(session_id)
      setPriorMessages([])
    } catch {
      setError('Could not start a new conversation. Please refresh the page.')
    }
  }, [])

  return { sessionId, priorMessages, isReady, error, resetSession }
}