import type { SearchFilters, SearchResponse, StoreSearchRequest, StoreSearchResponse, ChatMessage, SessionContext, ChatResponse, User, UserLocation, VoucherCard, InferredAttribute, FavoriteStore } from './types'
import { getAuthHeader } from './store/auth'

// In dev: leave VITE_API_URL unset → '' → relative URL '/api/*' goes through Vite proxy.
// In prod: set VITE_API_URL=https://api.<domain> in Vercel → calls go cross-origin (CORS-allowed).
const API_BASE = import.meta.env.VITE_API_URL ?? ''
const BASE = `${API_BASE}/api`

export async function searchProduct(query: string, filters: SearchFilters): Promise<SearchResponse> {
  const res = await fetch(`${BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
    body: JSON.stringify({ query, filters }),
  })
  if (!res.ok) throw new Error(`Search failed: ${res.status}`)
  return res.json()
}

export async function searchStores(req: StoreSearchRequest): Promise<StoreSearchResponse> {
  const res = await fetch(`${BASE}/stores/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error('Store search failed')
  return res.json()
}

export async function geocodeAddress(address: string): Promise<{ lat: number; lng: number; display_name: string }> {
  const res = await fetch(`${BASE}/geocode?address=${encodeURIComponent(address)}`, {
    headers: { ...getAuthHeader() },
  })
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
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
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

// Auth functions
export async function register(email: string, password: string, displayName?: string): Promise<{ token: string; user: User }> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Registration failed');
  return res.json();
}

export async function login(email: string, password: string): Promise<{ token: string; user: User }> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Login failed');
  return res.json();
}

export async function getMe(): Promise<User> {
  const res = await fetch(`${BASE}/auth/me`, {
    headers: { ...getAuthHeader() },
  });
  if (!res.ok) throw new Error('Unauthorized');
  return res.json();
}

export async function importSession(sessionHistory: Array<{role: string; content: string}>, sessionContext: Record<string, unknown> | null): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/auth/import-session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
    body: JSON.stringify({ session_history: sessionHistory, session_context: sessionContext }),
  });
  if (!res.ok) throw new Error('Import failed');
  return res.json();
}

export async function getInferred(): Promise<InferredAttribute[]> {
  const res = await fetch(`${BASE}/users/me/inferred`, { headers: { ...getAuthHeader() } });
  if (!res.ok) return [];
  return res.json();
}

export async function deleteInferred(id: string): Promise<void> {
  await fetch(`${BASE}/users/me/inferred/${id}`, { method: 'DELETE', headers: { ...getAuthHeader() } });
}

export async function confirmInferred(id: string): Promise<void> {
  await fetch(`${BASE}/users/me/inferred/${id}/confirm`, { method: 'PUT', headers: { ...getAuthHeader() } });
}

export async function updatePreferences(prefs: Record<string, string>): Promise<void> {
  await fetch(`${BASE}/users/me/preferences`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
    body: JSON.stringify(prefs),
  });
}

export async function getLocations(): Promise<UserLocation[]> {
  const res = await fetch(`${BASE}/users/me/locations`, { headers: { ...getAuthHeader() } });
  if (!res.ok) return [];
  return res.json();
}

export async function getVouchers(): Promise<VoucherCard[]> {
  const res = await fetch(`${BASE}/users/me/vouchers`, { headers: { ...getAuthHeader() } });
  if (!res.ok) return [];
  return res.json();
}

export async function getSearchHistory(): Promise<{ message: string; searched_at: string }[]> {
  const res = await fetch(`${BASE}/users/me/history`, { headers: { ...getAuthHeader() } });
  if (!res.ok) return [];
  return res.json();
}

export async function clearSearchHistory(): Promise<void> {
  await fetch(`${BASE}/users/me/history`, { method: 'DELETE', headers: { ...getAuthHeader() } });
}

export async function addFavorite(storeId: string, note?: string): Promise<void> {
  await fetch(`${BASE}/users/me/favorites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
    body: JSON.stringify({ store_id: storeId, note }),
  });
}

export async function getFavorites(): Promise<FavoriteStore[]> {
  const res = await fetch(`${BASE}/users/me/favorites`, { headers: { ...getAuthHeader() } });
  if (!res.ok) return [];
  return res.json();
}
