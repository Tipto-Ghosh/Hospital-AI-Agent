import {API_URL} from '../utils/constants';

export async function createSession(channel = 'web') {
  const resp = await fetch(`${API_URL}/api/v1/chat/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel }),
  })
  if (!resp.ok) throw new Error(`Failed to create session: ${resp.status}`)
  return resp.json() // { session_id, channel, started_at }
}

export async function getHistory(sessionId) {
  const resp = await fetch(`${API_URL}/api/v1/chat/history/${sessionId}`)
  if (!resp.ok) return { messages: [] }
  return resp.json() // { session_id, messages: [...] }
}