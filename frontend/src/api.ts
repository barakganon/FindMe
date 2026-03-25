import type { SearchFilters, SearchResponse } from './types'

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
