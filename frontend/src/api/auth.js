import { API_URL } from '../utils/constants'

export async function verifyIdentity({ sessionId, patientId, dateOfBirth, phoneLast4 }) {
  const resp = await fetch(`${API_URL}/api/v1/auth/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      patient_id: patientId,
      date_of_birth: dateOfBirth,
      phone_last4: phoneLast4,
    }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Verification failed')
  }
  return resp.json() // { session_token, expires_at, patient_id }
}

export async function endSession(sessionId) {
  await fetch(`${API_URL}/api/v1/auth/session/${sessionId}`, { method: 'DELETE' })
}