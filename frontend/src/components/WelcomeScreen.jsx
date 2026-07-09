const SUGGESTIONS = [
  'Book an appointment',
  'What are your visiting hours?',
  'I need to cancel my appointment',
  'Tell me about available services',
]

export default function WelcomeScreen({ onSuggestionClick }) {
  return (
    <div className="flex flex-col items-center justify-center text-center h-full px-6 py-10">
      <div className="w-12 h-12 rounded-full bg-hospital-blue text-white flex items-center justify-center font-bold text-lg mb-4">
        AI
      </div>
      <h1 className="text-lg font-semibold text-text-primary">
        Hello, I&apos;m the City General Hospital AI assistant.
      </h1>
      <p className="text-text-secondary mt-1 mb-6">I can help you with:</p>

      <div className="flex flex-wrap justify-center gap-2 max-w-md">
        {SUGGESTIONS.map((text) => (
          <button
            key={text}
            type="button"
            onClick={() => onSuggestionClick(text)}
            className="px-4 py-2 rounded-full border border-border-gray bg-surface-white text-sm text-hospital-navy hover:bg-surface-gray hover:border-hospital-blue transition-colors"
          >
            {text}
          </button>
        ))}
      </div>

      <p className="text-xs text-text-secondary mt-8 max-w-sm">
        For medical emergencies, call <span className="font-semibold">109</span> immediately. Do
        not rely on this chat for emergency care.
      </p>
    </div>
  )
}