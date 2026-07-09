import { AlertTriangle, Phone } from 'lucide-react'
import { FALLBACK_EMERGENCY_CONTACTS } from '../utils/constants'

export default function EmergencyBanner() {
  const { hotline, national, ambulance, location } = FALLBACK_EMERGENCY_CONTACTS

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="w-full bg-hospital-red text-white px-4 py-3 shrink-0"
    >
      <div className="flex items-start gap-3 max-w-3xl mx-auto">
        <AlertTriangle className="w-6 h-6 shrink-0 mt-0.5" aria-hidden="true" />
        <div className="flex-1 text-sm leading-relaxed">
          <p className="font-bold text-base mb-1">Medical Emergency Detected</p>
          <p>Call emergency services immediately:</p>
          <ul className="mt-1 space-y-0.5">
            <li>
              <span className="font-semibold">Hospital Emergency Hotline (24/7):</span> {hotline}
            </li>
            <li>
              <span className="font-semibold">National Emergency:</span> {national}
            </li>
            <li>
              <span className="font-semibold">Ambulance:</span> {ambulance}
            </li>
          </ul>
          <p className="mt-1">Go to the {location}</p>
        </div>
        <Phone className="w-6 h-6 shrink-0 mt-0.5" aria-hidden="true" />
      </div>
    </div>
  )
}