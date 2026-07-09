import { Wifi, WifiOff } from 'lucide-react'
import { CONNECTION_STATUS, HOSPITAL_NAME } from '../utils/constants'

const STATUS_TEXT = {
  [CONNECTION_STATUS.CONNECTED]: 'Connected',
  [CONNECTION_STATUS.CONNECTING]: 'Connecting…',
  [CONNECTION_STATUS.RECONNECTING]: 'Reconnecting…',
  [CONNECTION_STATUS.DISCONNECTED]: 'Disconnected',
}

const DOT_CLASSES = {
  [CONNECTION_STATUS.CONNECTED]: 'bg-hospital-green',
  [CONNECTION_STATUS.CONNECTING]: 'bg-hospital-amber animate-pulse-status',
  [CONNECTION_STATUS.RECONNECTING]: 'bg-hospital-amber animate-pulse-status',
  [CONNECTION_STATUS.DISCONNECTED]: 'bg-hospital-red',
}

export default function Header({ connectionStatus }) {
  const isOffline = connectionStatus === CONNECTION_STATUS.DISCONNECTED

  return (
    <header className="h-14 shrink-0 flex items-center justify-between px-4 bg-hospital-navy text-white">
      <div className="flex items-center gap-2">
        <span className="text-hospital-red bg-white rounded-sm w-5 h-5 flex items-center justify-center font-bold text-sm leading-none">
          +
        </span>
        <span className="font-bold text-base">{HOSPITAL_NAME}</span>
      </div>

      <div className="flex items-center gap-1.5 text-sm text-white/80">
        {isOffline ? (
          <WifiOff className="w-4 h-4" aria-hidden="true" />
        ) : (
          <Wifi className="w-4 h-4" aria-hidden="true" />
        )}
        <span className={`w-2 h-2 rounded-full ${DOT_CLASSES[connectionStatus]}`} aria-hidden="true" />
        <span className="hidden sm:inline">{STATUS_TEXT[connectionStatus]}</span>
      </div>
    </header>
  )
}