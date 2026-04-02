import { useState } from 'react'
import { ChatInterface } from './components/ChatInterface'
import type { SessionContext } from './types'

export default function App() {
  const [sessionContext, setSessionContext] = useState<SessionContext>({
    user_lat: null,
    user_lng: null,
    location_label: null,
    voucher_network: 'buyme',
  })

  return (
    <ChatInterface
      sessionContext={sessionContext}
      onLocationUpdate={setSessionContext}
    />
  )
}
