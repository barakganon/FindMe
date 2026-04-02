import type { SearchFilters, SearchResponse, StoreSearchRequest, StoreSearchResponse, ChatMessage, SessionContext, ChatResponse } from './types'

const BASE = '/api'

export async function searchProduct(query: string, filters: SearchFilters): Promise<SearchResponse> {
  const res = await fetch(`${BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, filters }),
  })
  if (!res.ok) throw new Error(`Search failed: ${res.status}`)
  return res.json()
}

export async function searchStores(req: StoreSearchRequest): Promise<StoreSearchResponse> {
  const res = await fetch(`${BASE}/stores/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error('Store search failed')
  return res.json()
}

export async function geocodeAddress(address: string): Promise<{ lat: number; lng: number; display_name: string }> {
  const res = await fetch(`${BASE}/geocode?address=${encodeURIComponent(address)}`)
  if (!res.ok) throw new Error('Geocoding failed')
  return res.json()
}

export async function sendChatMessage(
  message: string,
  history: ChatMessage[],
  sessionContext: SessionContext | null
): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      history,
      session_context: sessionContext,
      voucher_network: sessionContext?.voucher_network ?? 'buyme',
    }),
  })
  if (!res.ok) throw new Error('שגיאה בשליחת הודעה')
  return res.json()
}
