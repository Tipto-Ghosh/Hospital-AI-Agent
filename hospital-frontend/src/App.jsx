import { useMemo } from 'react'
import Header from './components/Header'
import StatusBar from './components/StatusBar'
import EmergencyBanner from './components/EmergencyBanner'
import ChatWindow from './components/ChatWindow'
import InputBar from './components/InputBar'
import { useSession } from './hooks/useSession'
import { useWebSocket } from './hooks/useWebSocket'
import { CONNECTION_STATUS, MAX_MESSAGE_LENGTH } from './utils/constants'

function App() {
  const { sessionId, priorMessages, isReady, error } = useSession()

  const {
    messages,
    streamingContent,
    streamingAgent,
    sendMessage,
    connectionStatus,
    isStreaming,
  } = useWebSocket(sessionId)

  // Prior history (from a restored session) is shown until the live
  // WebSocket-owned message list has its own entries for this page load.
  const allMessages = useMemo(
    () => (messages.length === 0 ? priorMessages : messages),
    [messages, priorMessages]
  )

  const isEmergency = allMessages.some((m) => m.is_emergency)

  if (!isReady && !error) {
    return (
      <div className="flex items-center justify-center h-screen-safe bg-surface-gray text-text-secondary">
        Connecting to City General Hospital…
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen-safe bg-surface-gray">
      <StatusBar status={connectionStatus} />
      <Header connectionStatus={connectionStatus} />

      {isEmergency && <EmergencyBanner />}

      {connectionStatus === CONNECTION_STATUS.DISCONNECTED && (
        <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-sm text-hospital-red shrink-0">
          Connection lost. Please refresh the page to reconnect.
        </div>
      )}

      {error && (
        <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-sm text-hospital-red shrink-0">
          {error}
        </div>
      )}

      <ChatWindow
        messages={allMessages}
        streamingContent={streamingContent}
        streamingAgent={streamingAgent}
        isStreaming={isStreaming}
        onSuggestionClick={sendMessage}
      />

      <InputBar
        onSend={sendMessage}
        disabled={isStreaming || !sessionId}
        maxLength={MAX_MESSAGE_LENGTH}
      />
    </div>
  )
}

export default App