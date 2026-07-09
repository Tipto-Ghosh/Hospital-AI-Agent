import { useEffect, useRef, useState } from 'react'
import MessageBubble from './MessageBubble'
import TypingIndicator from './TypingIndicator'
import WelcomeScreen from './WelcomeScreen'

const SCROLL_BOTTOM_THRESHOLD = 100

export default function ChatWindow({ messages, streamingContent, streamingAgent, isStreaming, onSuggestionClick }) {
  const containerRef = useRef(null)
  const messagesEndRef = useRef(null)
  const [autoScroll, setAutoScroll] = useState(true)

  useEffect(() => {
    if (!autoScroll) return
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent, autoScroll])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - (el.scrollTop + el.clientHeight)
    setAutoScroll(distanceFromBottom <= SCROLL_BOTTOM_THRESHOLD)
  }

  const showWelcome = messages.length === 0 && !isStreaming
  const showTypingIndicator = isStreaming && !streamingContent

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      role="log"
      aria-live="polite"
      className="chat-scroll flex-1 overflow-y-auto px-4 py-4 space-y-4"
    >
      {showWelcome && <WelcomeScreen onSuggestionClick={onSuggestionClick} />}

      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}

      {streamingContent && (
        <MessageBubble
          message={{
            id: 'streaming',
            role: 'ai',
            content: streamingContent,
            agent: streamingAgent,
            timestamp: null,
          }}
          isStreaming
        />
      )}

      {showTypingIndicator && <TypingIndicator />}

      <div ref={messagesEndRef} />
    </div>
  )
}