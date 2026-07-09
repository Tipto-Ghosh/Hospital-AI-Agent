import { AlertCircle } from 'lucide-react'
import { formatTimestamp, getAgentLabel } from '../utils/formatMessage'
import { MESSAGE_ROLES } from '../utils/constants'

export default function MessageBubble({ message, isStreaming = false }) {
  const { role, content, agent, timestamp } = message

  if (role === MESSAGE_ROLES.SYSTEM) {
    return <p className="text-center text-text-secondary italic text-sm py-1">{content}</p>
  }

  if (role === MESSAGE_ROLES.ERROR) {
    return (
      <div className="flex items-start gap-2 max-w-[75%] bg-amber-50 border border-hospital-amber/40 rounded-2xl rounded-bl-sm px-4 py-3">
        <AlertCircle className="w-4 h-4 text-hospital-amber shrink-0 mt-0.5" aria-hidden="true" />
        <p className="text-sm text-text-primary">
          {content || 'Something went wrong. Please try again.'}
        </p>
      </div>
    )
  }

  if (role === MESSAGE_ROLES.PATIENT) {
    return (
      <div className="flex flex-col items-end max-w-[70%] ml-auto">
        <div className="bg-hospital-blue text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-base leading-relaxed whitespace-pre-wrap break-words">
          {content}
        </div>
        <span className="text-xs text-text-secondary mt-1 mr-1">{formatTimestamp(timestamp)}</span>
      </div>
    )
  }

  // AI message
  const agentInfo = getAgentLabel(agent)

  return (
    <div className="flex items-end gap-2 max-w-[75%]">
      <div className="w-7 h-7 rounded-full bg-hospital-blue text-white text-[10px] font-bold flex items-center justify-center shrink-0 mb-5">
        AI
      </div>
      <div className="flex flex-col items-start">
        <div
          className={`bg-surface-white border border-border-gray shadow-sm rounded-2xl rounded-bl-sm px-4 py-2.5 text-base leading-relaxed text-text-primary whitespace-pre-wrap break-words ${
            isStreaming ? 'stream-cursor' : ''
          }`}
        >
          {content}
        </div>
        <div className="flex items-center gap-2 mt-1 ml-1">
          {agentInfo && (
            <span className="text-xs uppercase tracking-wide text-text-secondary">
              {agentInfo.icon} {agentInfo.label}
            </span>
          )}
          {!isStreaming && (
            <span className="text-xs text-text-secondary">{formatTimestamp(timestamp)}</span>
          )}
        </div>
      </div>
    </div>
  )
}