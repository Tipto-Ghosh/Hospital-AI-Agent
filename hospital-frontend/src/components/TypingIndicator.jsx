export default function TypingIndicator() {
  return (
    <div className="flex items-end gap-2 max-w-[75%]">
      <div className="w-7 h-7 rounded-full bg-hospital-blue text-white text-[10px] font-bold flex items-center justify-center shrink-0">
        AI
      </div>
      <div className="bg-surface-white border border-border-gray rounded-2xl rounded-bl-sm shadow-sm px-4 py-3 flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-text-secondary/60 animate-typing-dot-1" />
        <span className="w-2 h-2 rounded-full bg-text-secondary/60 animate-typing-dot-2" />
        <span className="w-2 h-2 rounded-full bg-text-secondary/60 animate-typing-dot-3" />
      </div>
    </div>
  )
}