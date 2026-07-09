import { AGENT_LABELS } from './constants'

export function formatTimestamp(date) {
  if (!date) return ''
  const d = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function getAgentLabel(agentName) {
  return AGENT_LABELS[agentName] ?? null
}