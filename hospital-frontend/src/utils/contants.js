export const API_URL = import.meta.env.VITE_API_URL ?? 'https://localhost'
export const WS_URL = import.meta.env.VITE_WS_URL ?? 'wss://localhost'
export const HOSPITAL_NAME = import.meta.env.VITE_HOSPITAL_NAME ?? 'City General Hospital'

export const WS_RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]
export const SESSION_STORAGE_KEY = 'hospital_session_id'
export const MAX_MESSAGE_LENGTH = 4000

export const CONNECTION_STATUS = {
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
  DISCONNECTED: 'disconnected',
}

export const MESSAGE_ROLES = {
  PATIENT: 'patient',
  AI: 'ai',
  SYSTEM: 'system',
  ERROR: 'error',
}

export const FALLBACK_EMERGENCY_CONTACTS = {
  hotline: '109',
  national: '999',
  ambulance: '01711-AMBU',
  location: 'Emergency Department — Ground Floor, Block A',
}

export const AGENT_LABELS = {
  info_agent: { icon: 'ℹ', label: 'Info' },
  booking_agent: { icon: '📅', label: 'Booking' },
  cancel_agent: { icon: '✕', label: 'Cancellation' },
  reschedule_agent: { icon: '🔄', label: 'Rescheduling' },
  records_agent: { icon: '📋', label: 'Medical Records' },
  billing_agent: { icon: '💳', label: 'Billing' },
  medication_agent: { icon: '💊', label: 'Medication' },
  feedback_agent: { icon: '⭐', label: 'Feedback' },
  emergency_agent: { icon: '🚨', label: 'Emergency Triage' },
  auth_agent: { icon: '🔐', label: 'Identity Verification' },
}