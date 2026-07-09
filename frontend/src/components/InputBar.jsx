import { Loader2, Send } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

const MAX_LINES = 5
const WARNING_THRESHOLD = 200

export default function InputBar({ onSend, disabled, maxLength }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const lineHeight = 24
    const maxHeight = lineHeight * MAX_LINES
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
  }, [text])

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const remaining = maxLength - text.length
  const showCounter = remaining <= WARNING_THRESHOLD

  return (
    <div className="border-t border-border-gray bg-surface-white px-3 py-2 shrink-0">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, maxLength))}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            rows={1}
            placeholder="Type your message…"
            aria-label="Message"
            className="w-full resize-none rounded-2xl border border-border-gray bg-surface-gray px-4 py-2.5 text-text-primary placeholder-text-secondary focus:outline-none focus:ring-2 focus:ring-hospital-blue disabled:opacity-60"
          />
          {showCounter && (
            <span
              className={`absolute -top-5 right-1 text-xs ${
                remaining < 0 ? 'text-hospital-red' : 'text-text-secondary'
              }`}
            >
              {remaining}
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={handleSend}
          disabled={disabled || !text.trim()}
          aria-label="Send message"
          className="w-10 h-10 shrink-0 rounded-full bg-hospital-blue text-white flex items-center justify-center disabled:opacity-40 hover:bg-hospital-blue/90 transition-colors"
        >
          {disabled ? (
            <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="w-5 h-5" aria-hidden="true" />
          )}
        </button>
      </div>
    </div>
  )
}