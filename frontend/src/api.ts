import type {
  SearchFilters, SearchResponse, StoreSearchRequest, StoreSearchResponse,
  ChatMessage, SessionContext, ChatResponse, ChatResponseV2,
  StreamThinking, ToolCallTrace, StreamError,
  User, UserLocation, VoucherCard, InferredAttribute, FavoriteStore,
} from './types'
import { getAuthHeader } from './store/auth'

// In dev: leave VITE_API_URL unset → '' → relative URL '/api/*' goes through Vite proxy.
// In prod: set VITE_API_URL=https://api.<domain> in Vercel → calls go cross-origin (CORS-allowed).
const API_BASE = import.meta.env.VITE_API_URL ?? ''
const BASE = `${API_BASE}/api`

// --- Session ID (W7) -------------------------------------------------------
// Single source of truth for the anon session id sent as X-Session-ID. Used
// by both streamChatV2 and sendChatMessage so we never race on first-load
// generation. Persists forever in localStorage; survives auth changes.

const SESSION_ID_KEY = 'findme_session_id'

export function getOrCreateSessionId(): string {
  try {
    const existing = localStorage.getItem(SESSION_ID_KEY)
    if (existing) return existing
    const id = (crypto.randomUUID && crypto.randomUUID()) || _fallbackUuid()
    localStorage.setItem(SESSION_ID_KEY, id)
    return id
  } catch {
    // Private mode / Safari quirks — return a fresh non-persistent id
    return _fallbackUuid()
  }
}

function _fallbackUuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

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
    headers: {
      'Content-Type': 'application/json',
      'X-Session-ID': getOrCreateSessionId(),
      ...getAuthHeader(),
    },
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

// --- W7: streaming v2 chat -------------------------------------------------

export interface StreamCallbacks {
  onThinking?: (e: StreamThinking) => void
  onToolCall?: (e: ToolCallTrace) => void
  onFinal: (response: ChatResponseV2) => void
  onError?: (e: StreamError | Error) => void
  /** Called when 503 cost-budget triggers transparent v1 fallback. */
  onFallback?: () => void
}

export interface StreamHandle {
  cancel(): void
}

/**
 * Stream a v2 chat turn via POST /api/chat/v2/stream (SSE). On HTTP 503 with
 * the cost-budget body, transparently falls back to v1 /api/chat and synthesizes
 * a fake final event so the UI loop is unchanged.
 *
 * SSE events handled: thinking, tool_call, final, error. partial_content is
 * accepted defensively for future token-streaming but currently never emitted
 * by the backend.
 */
export function streamChatV2(
  message: string,
  history: ChatMessage[],
  sessionContext: SessionContext | null,
  callbacks: StreamCallbacks,
): StreamHandle {
  const controller = new AbortController()
  void (async () => {
    try {
      const resp = await fetch(`${BASE}/chat/v2/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          'X-Session-ID': getOrCreateSessionId(),
          ...getAuthHeader(),
        },
        body: JSON.stringify({
          message,
          history,
          session_context: sessionContext,
          voucher_network: sessionContext?.voucher_network ?? 'buyme',
        }),
        signal: controller.signal,
      })

      // 503 = cost guard fired. Body is {error, fallback: "/api/chat"}.
      // Transparently re-issue against v1 and synthesize a ChatResponseV2.
      if (resp.status === 503) {
        callbacks.onFallback?.()
        await _fallbackToV1(message, history, sessionContext, callbacks)
        return
      }

      if (!resp.ok || !resp.body) {
        const text = await resp.text().catch(() => '')
        throw new Error(`stream HTTP ${resp.status}${text ? `: ${text.slice(0, 200)}` : ''}`)
      }

      await _consumeSse(resp.body, callbacks)
    } catch (err) {
      if ((err as { name?: string }).name === 'AbortError') return
      callbacks.onError?.(err as Error)
    }
  })()
  return { cancel: () => controller.abort() }
}

async function _consumeSse(stream: ReadableStream<Uint8Array>, cb: StreamCallbacks): Promise<void> {
  const reader = stream.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  // SSE frames are separated by a blank line (\n\n). A single read() may
  // contain multiple frames or only part of one — buffer until we see a
  // boundary, then process complete frames.
  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      // Flush any trailing complete frame
      if (buffer.trim()) _dispatchFrame(buffer, cb)
      return
    }
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      if (frame.trim()) _dispatchFrame(frame, cb)
    }
  }
}

function _dispatchFrame(frame: string, cb: StreamCallbacks): void {
  let event: string | null = null
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!event || dataLines.length === 0) return
  let payload: unknown
  try {
    payload = JSON.parse(dataLines.join('\n'))
  } catch {
    return
  }
  switch (event) {
    case 'thinking':
      cb.onThinking?.(payload as StreamThinking)
      break
    case 'tool_call':
      cb.onToolCall?.(payload as ToolCallTrace)
      break
    case 'final':
      cb.onFinal(payload as ChatResponseV2)
      break
    case 'error':
      cb.onError?.(payload as StreamError)
      break
    // partial_content is reserved for future token-level streaming
  }
}

async function _fallbackToV1(
  message: string,
  history: ChatMessage[],
  sessionContext: SessionContext | null,
  cb: StreamCallbacks,
): Promise<void> {
  try {
    const v1 = await sendChatMessage(message, history, sessionContext)
    // Synthesize a ChatResponseV2 shape so the UI doesn't care which path served us.
    const synthesized: ChatResponseV2 = {
      message: v1.message,
      intent: v1.intent,
      product_results: v1.product_results,
      store_results: v1.store_results,
      needs_location: v1.needs_location,
      location_prompt: v1.location_prompt,
      voucher_network: v1.voucher_network,
      search_time_ms: v1.search_time_ms,
      chips: [],
      trace: { tool_calls: [], iterations: 0, total_latency_ms: 0, total_cost_usd: null, terminated_by: 'content' },
    }
    cb.onFinal(synthesized)
  } catch (err) {
    cb.onError?.(err as Error)
  }
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
