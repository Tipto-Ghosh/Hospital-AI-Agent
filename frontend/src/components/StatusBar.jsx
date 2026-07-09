import { CONNECTION_STATUS } from '../utils/constants'

const LINE_CLASSES = {
  [CONNECTION_STATUS.CONNECTED]: 'bg-hospital-green',
  [CONNECTION_STATUS.CONNECTING]: 'bg-hospital-amber animate-pulse-status',
  [CONNECTION_STATUS.RECONNECTING]: 'bg-hospital-amber animate-pulse-status',
  [CONNECTION_STATUS.DISCONNECTED]: 'bg-hospital-red',
}

export default function StatusBar({ status }) {
  const lineClass = LINE_CLASSES[status] ?? LINE_CLASSES[CONNECTION_STATUS.CONNECTING]
  const title =
    status === CONNECTION_STATUS.RECONNECTING
      ? 'Reconnecting…'
      : status === CONNECTION_STATUS.DISCONNECTED
        ? 'Connection lost. Refresh the page.'
        : undefined

  return <div className={`h-1 w-full shrink-0 ${lineClass}`} title={title} aria-hidden="true" />
}