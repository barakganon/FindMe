/**
 * ChatInterface — v2 agentic chat UI (W7).
 *
 * Layout: 60% chat / 40% tray on ≥768px (flex-row with dir="rtl" → tray ends up
 * on the right naturally). On <768px the tray collapses to a header strip below
 * the chat; user can toggle open/closed and the choice persists in localStorage.
 *
 * Streaming: POST /api/chat/v2/stream via fetch + ReadableStream (NOT EventSource,
 * which is GET-only). The streamChatV2 helper handles 503 → v1 fallback transparently.
 *
 * State surfaces above and around the conversation:
 *  - Memory chip strip (from final.chips) above the messages list
 *  - In-flight assistant bubble shows a state line synthesized from onThinking +
 *    onToolCall events: חושב… → מחפש בקטלוג… / מאתר העדפות… / נזכר… → מסנן…
 *  - When final.intent differs from the previous assistant's intent and there's
 *    history, the new bubble gets a subtitle: "החלפת נושא? התוצאות הקודמות עדיין שמורות במגש"
 *  - Tray accumulates products + stores across all turns, deduped by (type, id),
 *    capped at 20. Persists in localStorage.findme_tray.
 *
 * Preserved from the v1 component:
 *  - Welcome message + suggestion chips (first load only)
 *  - Inline GPS button when response.needs_location=true
 *  - Soft-registration prompt after the 3rd user message
 *  - ProfileDrawer + avatar header button
 *  - Existing ResultCard / StoreCard / StoreMap inside assistant bubbles
 */

import { useState, useRef, useEffect } from 'react'
import { streamChatV2, sendChatMessage, getMe, register, importSession } from '../api'
import type {
  ChatMessage, SessionContext, ProductResult, StoreResult, User,
  ChatResponseV2, MemoryChip, ToolCallTrace, StreamThinking, StreamError,
} from '../types'
import {
  getSavedToken, saveAuth, clearAuth,
  isRegistrationDismissed, dismissRegistration,
} from '../store/auth'
import { ResultCard } from './ResultCard'
import { StoreCard } from './StoreCard'
import { StoreMap } from './StoreMap'
import ProfileDrawer from './ProfileDrawer'

interface Props {
  sessionContext: SessionContext | null
  onLocationUpdate: (ctx: SessionContext) => void
}

// --- Chat-entry model ------------------------------------------------------

interface AssistantEntry {
  role: 'assistant'
  content: string
  response?: ChatResponseV2
  intent?: string
  topicChanged?: boolean
  // The user prompt that triggered this assistant turn. Used by the inline GPS
  // button to resend the *original* message even if turns have interleaved
  // since the bubble was rendered (otherwise `lastMessage` is stale).
  originPrompt?: string
  // Marks bubbles produced by client-side error paths. Filtered out of LLM
  // history so the agent doesn't see its own error messages as prior turns.
  isError?: boolean
}
interface UserEntry {
  role: 'user'
  content: string
}
type ChatEntry = UserEntry | AssistantEntry

// --- Tray model ------------------------------------------------------------

type TrayItem =
  | { type: 'product'; id: string; addedAt: number; item: ProductResult }
  | { type: 'store'; id: string; addedAt: number; item: StoreResult }

interface TrayBlob {
  v: number
  items: TrayItem[]
}

const TRAY_KEY = 'findme_tray'
const TRAY_OPEN_KEY = 'findme_tray_open'
const FALLBACK_NOTICE_KEY = 'findme_fallback_notice_shown'
const TRAY_MAX = 20
// Bump when TrayItem shape changes incompatibly — older blobs are discarded
// rather than rendered into <ResultCard result={undefined}>.
const TRAY_SCHEMA_VERSION = 1

const WELCOME_MESSAGE = (name?: string | null): AssistantEntry => ({
  role: 'assistant',
  content: name
    ? `שלום ${name}! מה תרצה למצוא היום? 🔍`
    : 'שלום! 👋 אני FindMe. תגיד לי מה אתה מחפש ואני אמצא היכן להשתמש בכרטיס BuyMe שלך.',
})

const SUGGESTION_CHIPS = [
  '🍽️ מסעדות בתל אביב',
  '🎧 אוזניות סוני',
  '👗 חנויות אופנה לידי',
  '💄 ספא וטיפוח',
]

// --- Streaming state line helpers -----------------------------------------

interface StreamingState {
  stage: 'thinking' | 'tool' | 'composing'
  tool?: string
}

function streamingLabel(s: StreamingState | null): string {
  if (!s) return ''
  if (s.stage === 'thinking') return 'חושב…'
  if (s.stage === 'composing') return 'מסנן…'
  // s.stage === 'tool'
  switch (s.tool) {
    case 'search_products':
    case 'search_stores':
      return 'מחפש בקטלוג…'
    case 'get_user_context':
      return 'מאתר העדפות…'
    case 'recall_history':
      return 'נזכר בשיחה…'
    case 'clarify':
      return 'מבקש פרטים…'
    default:
      return 'עובד…'
  }
}

// --- Tray helpers ----------------------------------------------------------

function loadTray(): TrayItem[] {
  try {
    const raw = localStorage.getItem(TRAY_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    // New format: { v, items }. Older format (v0): bare array — discard on
    // version mismatch rather than render undefined items.
    if (
      parsed && typeof parsed === 'object' && !Array.isArray(parsed) &&
      parsed.v === TRAY_SCHEMA_VERSION && Array.isArray(parsed.items)
    ) {
      return (parsed.items as TrayItem[]).filter(_isValidTrayItem).slice(0, TRAY_MAX)
    }
    // Unknown shape — discard and start fresh
    return []
  } catch {
    return []
  }
}

function _isValidTrayItem(it: unknown): it is TrayItem {
  if (!it || typeof it !== 'object') return false
  const x = it as { type?: unknown; id?: unknown; item?: unknown }
  return (
    (x.type === 'product' || x.type === 'store') &&
    typeof x.id === 'string' &&
    x.item != null && typeof x.item === 'object'
  )
}

function saveTray(items: TrayItem[]): void {
  try {
    const blob: TrayBlob = { v: TRAY_SCHEMA_VERSION, items: items.slice(0, TRAY_MAX) }
    localStorage.setItem(TRAY_KEY, JSON.stringify(blob))
  } catch {
    // private mode etc — silently drop
  }
}

function mergeIntoTray(
  current: TrayItem[],
  products: ProductResult[] | null,
  stores: StoreResult[] | null,
): TrayItem[] {
  const now = Date.now()
  // Index by (type, id) for dedup
  const byKey = new Map<string, TrayItem>()
  for (const it of current) byKey.set(`${it.type}:${it.id}`, it)

  for (const p of products ?? []) {
    // Prefer the stable UUID. Synthesized fallback is only used when the
    // result is missing both id forms — extremely rare; we use the stable
    // store-id + product_url combo (URL differs per variant) so distinct
    // variants do NOT collapse into one tray slot.
    const explicitId = (p as { product_id?: string; id?: string }).product_id
      ?? (p as { id?: string }).id
    const variantKey = p.product_url ?? p.canonical_name
    const id = explicitId && explicitId.length > 0
      ? explicitId
      : (p.store?.id && variantKey ? `${p.store.id}|${variantKey}` : null)
    if (!id) continue
    const key = `product:${id}`
    if (!byKey.has(key)) byKey.set(key, { type: 'product', id, addedAt: now, item: p })
  }
  for (const s of stores ?? []) {
    const id = s.id
    if (!id) continue
    const key = `store:${id}`
    if (!byKey.has(key)) byKey.set(key, { type: 'store', id, addedAt: now, item: s })
  }

  // Newest first, cap at TRAY_MAX
  return Array.from(byKey.values())
    .sort((a, b) => b.addedAt - a.addedAt)
    .slice(0, TRAY_MAX)
}

// --- Component -------------------------------------------------------------

export function ChatInterface({ sessionContext, onLocationUpdate }: Props) {
  const [currentUser, setCurrentUser] = useState<User | null>(null)
  const [messages, setMessages] = useState<ChatEntry[]>([WELCOME_MESSAGE(null)])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [streamingState, setStreamingState] = useState<StreamingState | null>(null)
  const [chipsVisible, setChipsVisible] = useState(true)
  const [lastMessage, setLastMessage] = useState<string>('')
  const [chipStrip, setChipStrip] = useState<MemoryChip[]>([])
  const [tray, setTray] = useState<TrayItem[]>(loadTray)
  const [trayOpenMobile, setTrayOpenMobile] = useState<boolean>(() => {
    try { return localStorage.getItem(TRAY_OPEN_KEY) === 'true' } catch { return false }
  })
  const [showFallbackNotice, setShowFallbackNotice] = useState(false)
  const [showRegPrompt, setShowRegPrompt] = useState(false)
  const [showRegForm, setShowRegForm] = useState(false)
  const [regEmail, setRegEmail] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [regName, setRegName] = useState('')
  const [regError, setRegError] = useState('')
  const [profileOpen, setProfileOpen] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const userMessageCount = useRef(0)
  const lastIntent = useRef<string | null>(null)
  // Track in-flight stream + timers per turn so we can cancel cleanly on
  // unmount, on a new send, and on success/error.
  const activeHandleRef = useRef<{ cancel(): void } | null>(null)
  const settleTimerRef = useRef<number | null>(null)
  const safetyTimerRef = useRef<number | null>(null)
  const isMountedRef = useRef(true)

  // Load existing auth on mount
  useEffect(() => {
    const token = getSavedToken()
    if (token) {
      getMe()
        .then(user => {
          setCurrentUser(user)
          setMessages([WELCOME_MESSAGE(user.display_name)])
        })
        .catch(() => clearAuth())
    }
  }, [])

  // Mark fallback-notice as shown only for this tab session
  useEffect(() => {
    try {
      if (sessionStorage.getItem(FALLBACK_NOTICE_KEY) === '1') setShowFallbackNotice(false)
    } catch { /* ignore */ }
  }, [])

  // Persist tray
  useEffect(() => { saveTray(tray) }, [tray])

  // Persist mobile tray open/closed
  useEffect(() => {
    try { localStorage.setItem(TRAY_OPEN_KEY, String(trayOpenMobile)) } catch { /* ignore */ }
  }, [trayOpenMobile])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingState])

  // Cancel in-flight stream + timers on unmount so stale callbacks don't
  // mutate state after the component is gone.
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      activeHandleRef.current?.cancel()
      activeHandleRef.current = null
      if (settleTimerRef.current !== null) window.clearTimeout(settleTimerRef.current)
      if (safetyTimerRef.current !== null) window.clearTimeout(safetyTimerRef.current)
      settleTimerRef.current = null
      safetyTimerRef.current = null
    }
  }, [])

  const currentSession: SessionContext = sessionContext ?? {
    user_lat: null,
    user_lng: null,
    location_label: null,
    voucher_network: 'buyme',
  }

  const requestGPS = (resendMessage?: string) => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const updated: SessionContext = {
          ...currentSession,
          user_lat: pos.coords.latitude,
          user_lng: pos.coords.longitude,
          location_label: 'המיקום שלי',
        }
        onLocationUpdate(updated)
        if (resendMessage) sendMessage(resendMessage, updated)
      },
      () => { /* user denied — silently ignore */ },
    )
  }

  // Clears any pending settle/safety timers for the previous (or current) turn.
  const clearPendingTimers = () => {
    if (settleTimerRef.current !== null) {
      window.clearTimeout(settleTimerRef.current)
      settleTimerRef.current = null
    }
    if (safetyTimerRef.current !== null) {
      window.clearTimeout(safetyTimerRef.current)
      safetyTimerRef.current = null
    }
  }

  const sendMessage = async (text: string, overrideSession?: SessionContext) => {
    if (!text.trim() || loading) return

    // A new send invalidates any prior in-flight turn's timers/handle. Without
    // this, a 200ms settle or 30s safety from the previous turn can land in
    // the middle of this one and graft prior results onto the new conversation.
    activeHandleRef.current?.cancel()
    activeHandleRef.current = null
    clearPendingTimers()

    const session = overrideSession ?? currentSession

    // History: last 10 messages, but EXCLUDE error bubbles — otherwise the
    // LLM sees its own "מצטער, אירעה שגיאה…" as prior assistant content.
    const history: ChatMessage[] = messages
      .filter((m) => !(m.role === 'assistant' && (m as AssistantEntry).isError))
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.content }))

    const userEntry: UserEntry = { role: 'user', content: text }
    setMessages((prev) => [...prev, userEntry])
    setLastMessage(text)
    setLoading(true)
    setChipsVisible(false)
    setStreamingState({ stage: 'thinking' })

    userMessageCount.current += 1
    if (userMessageCount.current === 3 && !currentUser && !isRegistrationDismissed()) {
      setShowRegPrompt(true)
    }

    // Per-turn flags — captured in closures so they don't race with concurrent
    // turn state. `originPrompt` is stamped into the produced assistant entry
    // so the inline GPS button later resends THIS message, not a stale `lastMessage`.
    let firstToolSeen = false
    const originPrompt = text

    const finishTurn = () => {
      clearPendingTimers()
      activeHandleRef.current = null
      if (!isMountedRef.current) return
      setStreamingState(null)
      setLoading(false)
      textareaRef.current?.focus()
    }

    const handle = streamChatV2(text, history, session, {
      onThinking: (e: StreamThinking) => {
        if (!isMountedRef.current) return
        setStreamingState({ stage: e.stage === 'composing' ? 'composing' : 'thinking' })
      },
      onToolCall: (tc: ToolCallTrace) => {
        if (!isMountedRef.current) return
        firstToolSeen = true
        setStreamingState({ stage: 'tool', tool: tc.name })
      },
      onFinal: (resp: ChatResponseV2) => {
        // settleFinal runs after a brief composing pulse (when a tool fired)
        // or immediately (for zero-tool turns).
        const settleFinal = () => {
          settleTimerRef.current = null
          if (!isMountedRef.current) return

          const priorIntent = lastIntent.current
          const respIntent = resp.intent ?? null
          // Topic-change banner: ignore error-class intents on both sides so
          // a transient error doesn't cascade a "החלפת נושא?" badge into the
          // next legitimate turn.
          const isErrorIntent = (i: string | null) => i === 'error' || i === null
          const topicChanged = Boolean(
            !isErrorIntent(priorIntent) &&
              !isErrorIntent(respIntent) &&
              priorIntent !== respIntent,
          )
          if (!isErrorIntent(respIntent)) lastIntent.current = respIntent

          const assistantEntry: AssistantEntry = {
            role: 'assistant',
            content: resp.message,
            response: resp,
            intent: resp.intent,
            topicChanged,
            originPrompt,
          }
          setMessages((prev) => [...prev, assistantEntry])
          setChipStrip(resp.chips ?? [])
          setTray((prev) => mergeIntoTray(prev, resp.product_results, resp.store_results))
          finishTurn()
        }
        if (firstToolSeen) {
          if (isMountedRef.current) setStreamingState({ stage: 'composing' })
          settleTimerRef.current = window.setTimeout(settleFinal, 200)
        } else {
          settleFinal()
        }
      },
      onError: (e: StreamError | Error) => {
        if (!isMountedRef.current) {
          finishTurn()
          return
        }
        const detail = 'error' in e ? e.error : e.message
        const errorEntry: AssistantEntry = {
          role: 'assistant',
          content: `מצטער, אירעה שגיאה: ${detail}. נסה שנית.`,
          isError: true,
        }
        setMessages((prev) => [...prev, errorEntry])
        finishTurn()
      },
      onFallback: () => {
        if (!isMountedRef.current) return
        try {
          if (sessionStorage.getItem(FALLBACK_NOTICE_KEY) !== '1') {
            setShowFallbackNotice(true)
            sessionStorage.setItem(FALLBACK_NOTICE_KEY, '1')
          }
        } catch { setShowFallbackNotice(true) }
      },
    })

    activeHandleRef.current = handle

    // Safety timer: if neither final nor error arrives in 30s, surface an error.
    // Guarded with the handle ref — if a new turn already replaced the handle,
    // this is a no-op.
    safetyTimerRef.current = window.setTimeout(() => {
      safetyTimerRef.current = null
      if (activeHandleRef.current !== handle) return  // superseded by next turn
      handle.cancel()
      if (!isMountedRef.current) return
      const errorEntry: AssistantEntry = {
        role: 'assistant',
        content: 'הבקשה לקחה יותר מדי זמן. נסה שנית.',
        isError: true,
      }
      setMessages((prev) => [...prev, errorEntry])
      finishTurn()
    }, 30_000)
  }

  const handleSend = () => {
    const text = inputValue.trim()
    if (!text || loading) return
    setInputValue('')
    void sendMessage(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleChipClick = (chip: string) => {
    setInputValue('')
    void sendMessage(chip)
  }

  const handleClearTray = () => {
    setTray([])
    try { localStorage.removeItem(TRAY_KEY) } catch { /* ignore */ }
  }

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setRegError('')
    try {
      const result = await register(regEmail, regPassword, regName || undefined)
      saveAuth(result.token, result.user)
      setCurrentUser(result.user)
      await importSession(
        messages
          .filter(m => m.role !== 'assistant' || !(m as AssistantEntry).response)
          .map(m => ({ role: m.role, content: m.content })),
        sessionContext as Record<string, unknown> | null
      ).catch(() => { /* ignore — best-effort */ })
      setShowRegPrompt(false)
      setShowRegForm(false)
    } catch (err: unknown) {
      setRegError(err instanceof Error ? err.message : 'שגיאה ברישום')
    }
  }

  // --- Render ----------------------------------------------------------------

  return (
    <div
      className="flex flex-col h-screen bg-gray-50"
      dir="rtl"
      lang="he"
      style={{ fontFamily: "-apple-system, 'Segoe UI', sans-serif" }}
    >
      {/* Header */}
      <header
        className="bg-white border-b border-gray-100 shadow-sm flex items-center justify-between px-4 shrink-0"
        style={{ height: '56px' }}
      >
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-blue-600">🔍 FindMe</span>
          <span className="text-gray-400 text-sm hidden sm:inline">חיפוש חכם לכרטיסי BuyMe</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="bg-blue-600 text-white text-xs font-medium px-2 py-1 rounded-full">BuyMe ✓</span>
          <button
            onClick={() => setProfileOpen(true)}
            className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white ${
              currentUser ? 'bg-blue-600' : 'bg-gray-300'
            }`}
            title={currentUser ? currentUser.display_name || currentUser.email : 'התחבר'}
            aria-label={currentUser ? `פרופיל: ${currentUser.display_name || currentUser.email}` : 'התחבר / פרופיל'}
          >
            {currentUser ? (currentUser.display_name || currentUser.email)[0].toUpperCase() : '👤'}
          </button>
        </div>
      </header>

      {/* Two-column split (chat + tray). On mobile this stacks vertically. */}
      <div className="flex flex-col md:flex-row flex-1 min-h-0">
        {/* CHAT COLUMN — first in DOM. With dir="rtl" the visual order in flex-row
            is reversed, so this column ends up on the LEFT visually. */}
        <div className="flex-1 md:flex-[6] flex flex-col min-h-0">
          {/* Chip strip — hidden when empty */}
          {chipStrip.length > 0 && (
            <div className="bg-white border-b border-gray-100 px-3 py-2 flex gap-2 overflow-x-auto shrink-0">
              {chipStrip.map((chip, i) => (
                <span
                  key={`${chip.kind}-${chip.label}-${i}`}
                  className={`flex-shrink-0 rounded-full text-sm px-3 py-1 flex items-center gap-1 ${
                    chip.confirmed
                      ? 'bg-blue-100 text-blue-800 ring-1 ring-blue-200'
                      : 'bg-blue-50 text-blue-700'
                  }`}
                  // Intentionally NO title= here — `chip.source` can contain
                  // the raw user message that triggered the inference, which
                  // would leak as a tooltip on shoulder-surfed/shared screens.
                  // The source field stays in the response payload for backend
                  // debugging and the ProfileDrawer's transparency view only.
                >
                  <span>{chip.icon}</span>
                  <span>{chip.label}</span>
                </span>
              ))}
            </div>
          )}

          {/* v1-fallback notice */}
          {showFallbackNotice && (
            <div className="bg-gray-50 px-3 py-1 text-xs text-gray-500 italic shrink-0 text-center">
              מצב מבוסס במקום סוכן (מגבלת עלות יומית)
            </div>
          )}

          {/* Messages area */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            {messages.map((msg, index) => (
              <div key={index} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`flex flex-col gap-2 ${
                    msg.role === 'user'
                      ? 'items-end ml-auto max-w-[80%]'
                      : 'items-start mr-auto max-w-[85%]'
                  }`}
                >
                  {/* Topic-change subtitle (above bubble, assistant only) */}
                  {msg.role === 'assistant' && (msg as AssistantEntry).topicChanged && (
                    <div className="text-xs text-gray-500 italic px-2">
                      החלפת נושא? התוצאות הקודמות עדיין שמורות במגש.
                    </div>
                  )}

                  {/* Text bubble */}
                  <div
                    className={`px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                      msg.role === 'user'
                        ? 'bg-blue-600 text-white rounded-2xl rounded-tr-sm'
                        : 'bg-white border border-gray-100 shadow-sm text-gray-800 rounded-2xl rounded-tl-sm'
                    }`}
                  >
                    {msg.content}

                    {/* GPS prompt — inline inside assistant bubble */}
                    {msg.role === 'assistant' && (msg as AssistantEntry).response?.needs_location && (
                      <div className="mt-3">
                        {currentSession.user_lat != null ? (
                          <span className="text-xs text-green-700 flex items-center gap-1">
                            <span>✓</span>
                            <span>מיקום התקבל — שולח שוב...</span>
                          </span>
                        ) : (
                          <button
                            // Resend the message that produced THIS needs_location
                            // bubble — not `lastMessage`, which after interleaved
                            // sends would be a different turn's text entirely.
                            onClick={() => requestGPS(
                              (msg as AssistantEntry).originPrompt ?? lastMessage,
                            )}
                            className="inline-flex items-center gap-1 bg-blue-600 text-white text-xs font-medium px-3 py-1.5 rounded-full hover:bg-blue-700 transition-colors"
                          >
                            <span>📍</span>
                            <span>שתף מיקום</span>
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Latency badge */}
                  {msg.role === 'assistant' && (msg as AssistantEntry).response && (msg as AssistantEntry).response!.search_time_ms > 0 && (
                    <span className="text-xs text-gray-400 px-1">
                      נמצא תוך {Math.round((msg as AssistantEntry).response!.search_time_ms)} ms
                    </span>
                  )}

                  {/* Product results */}
                  {msg.role === 'assistant' && (msg as AssistantEntry).response?.product_results && (msg as AssistantEntry).response!.product_results!.length > 0 && (
                    <div className="w-full space-y-3">
                      <div className="flex overflow-x-auto gap-3 pb-2 sm:grid sm:grid-cols-3 sm:overflow-x-visible">
                        {(msg as AssistantEntry).response!.product_results!.slice(0, 6).map((r, i) => (
                          <div key={i} className="shrink-0 w-48 sm:w-auto">
                            <ResultCard result={r} />
                          </div>
                        ))}
                      </div>
                      {(msg as AssistantEntry).response!.product_results!.length > 6 && (
                        <p className="text-xs text-gray-400 text-center mt-1">
                          ועוד {(msg as AssistantEntry).response!.product_results!.length - 6} תוצאות נוספות
                        </p>
                      )}
                      {(msg as AssistantEntry).response!.product_results!.some((r) => r.store.lat != null) && (
                        <div className="rounded-xl overflow-hidden" style={{ height: '220px' }}>
                          <StoreMap results={(msg as AssistantEntry).response!.product_results!} mode="product" />
                        </div>
                      )}
                    </div>
                  )}

                  {/* Store results */}
                  {msg.role === 'assistant' && (msg as AssistantEntry).response?.store_results && (msg as AssistantEntry).response!.store_results!.length > 0 && (
                    <div className="w-full space-y-3">
                      <div className="flex overflow-x-auto gap-3 pb-2 sm:grid sm:grid-cols-3 sm:overflow-x-visible">
                        {(msg as AssistantEntry).response!.store_results!.slice(0, 6).map((s, i) => (
                          <div key={s.id ?? i} className="shrink-0 w-48 sm:w-auto">
                            <StoreCard result={s} />
                          </div>
                        ))}
                      </div>
                      {(msg as AssistantEntry).response!.store_results!.length > 6 && (
                        <p className="text-xs text-blue-600 text-center">
                          ועוד {(msg as AssistantEntry).response!.store_results!.length - 6} חנויות
                        </p>
                      )}
                      {(msg as AssistantEntry).response!.store_results!.some((s) => s.lat != null) && (
                        <div className="rounded-xl overflow-hidden" style={{ height: '220px' }}>
                          <StoreMap results={(msg as AssistantEntry).response!.store_results!} mode="store" />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* Registration prompt — after 3rd message */}
            {showRegPrompt && !currentUser && (
              <div className="flex justify-start mb-4">
                <div className="max-w-[85%] bg-white border border-gray-100 shadow-sm rounded-2xl rounded-tl-sm px-4 py-3">
                  <p className="text-sm text-gray-700 mb-3">רוצה שאזכור את ההעדפות שלך לפעם הבאה? 📝</p>
                  {!showRegForm ? (
                    <div className="flex gap-2">
                      <button onClick={() => setShowRegForm(true)} className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded-full">
                        צור חשבון
                      </button>
                      <button onClick={() => { setShowRegPrompt(false); dismissRegistration() }} className="px-3 py-1.5 bg-gray-100 text-gray-600 text-xs rounded-full">
                        המשך בלי חשבון
                      </button>
                    </div>
                  ) : (
                    <form onSubmit={handleRegisterSubmit} className="space-y-2">
                      <input value={regName} onChange={e => setRegName(e.target.value)} placeholder="שם (אופציונלי)" aria-label="שם (אופציונלי)" className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 text-right" dir="rtl" />
                      <input required type="email" value={regEmail} onChange={e => setRegEmail(e.target.value)} placeholder="אימייל" aria-label="אימייל" className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 text-right" dir="rtl" />
                      <input required type="password" value={regPassword} onChange={e => setRegPassword(e.target.value)} placeholder="סיסמה" aria-label="סיסמה" className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 text-right" dir="rtl" />
                      {regError && <p className="text-red-500 text-xs text-right">{regError}</p>}
                      <button type="submit" className="w-full py-1.5 bg-blue-600 text-white text-sm rounded-lg">הירשם</button>
                    </form>
                  )}
                </div>
              </div>
            )}

            {/* Suggestion chips — first load only */}
            {chipsVisible && messages.length === 1 && (
              <div className="flex flex-wrap gap-2 justify-center mt-2">
                {SUGGESTION_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    onClick={() => handleChipClick(chip)}
                    className="bg-white border border-gray-200 text-gray-700 text-sm px-4 py-2 rounded-full shadow-sm hover:border-blue-400 hover:text-blue-600 transition-colors"
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}

            {/* In-flight assistant bubble with streaming state line.
                Continuation badge appears above when we're mid-conversation
                AND the tray already has items — signals "I'm answering, and
                your previous results are still saved". */}
            {streamingState && (
              <div className="flex flex-col items-start" role="status" aria-live="polite" aria-atomic="true">
                {tray.length > 0 && messages.length > 2 && (
                  <div className="text-xs text-gray-400 italic mb-1 px-2">
                    המשך השיחה ↑
                  </div>
                )}
                <div className="bg-white border border-gray-100 shadow-sm rounded-2xl rounded-tl-sm px-4 py-3">
                  <span className="text-xs text-gray-400 italic">{streamingLabel(streamingState)}</span>
                </div>
              </div>
            )}

            {/* Loading fallback dots when stream is initiating before any
                event has arrived. `streamingState` is set synchronously to
                'thinking' in sendMessage, so this only renders during the brief
                async gap before React commits that state — useful when the
                whole stream is delayed (slow network, cold backend). */}
            {loading && streamingState === null && (
              <div className="flex justify-start">
                <div className="bg-white border border-gray-100 shadow-sm rounded-2xl rounded-tl-sm px-5 py-3">
                  <span className="inline-flex gap-1 items-center">
                    <span className="animate-bounce text-gray-400 text-lg" style={{ animationDelay: '0ms' }}>•</span>
                    <span className="animate-bounce text-gray-400 text-lg" style={{ animationDelay: '150ms' }}>•</span>
                    <span className="animate-bounce text-gray-400 text-lg" style={{ animationDelay: '300ms' }}>•</span>
                  </span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Location status bar (above input) */}
          {currentSession.location_label && (
            <div className="px-4 py-1.5 bg-green-50 border-t border-green-100 flex items-center justify-between text-xs text-green-700 shrink-0">
              <span>📍 {currentSession.location_label}</span>
              <button
                onClick={() => onLocationUpdate({ ...currentSession, user_lat: null, user_lng: null, location_label: null })}
                className="text-gray-400 hover:text-red-500 transition-colors mr-2"
                aria-label="נקה מיקום"
              >
                ✕
              </button>
            </div>
          )}

          {/* Input bar */}
          <div className="bg-white border-t border-gray-200 shadow-[0_-2px_8px_rgba(0,0,0,0.06)] px-4 py-3 shrink-0" style={{ minHeight: '64px' }}>
            <div className="flex items-center gap-2 max-w-3xl mx-auto">
              <button
                onClick={handleSend}
                disabled={loading || !inputValue.trim()}
                className="shrink-0 flex items-center justify-center w-10 h-10 bg-blue-600 text-white rounded-full hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                aria-label="שלח"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                  <path fillRule="evenodd" d="M11.47 2.47a.75.75 0 011.06 0l7.5 7.5a.75.75 0 11-1.06 1.06l-6.22-6.22V21a.75.75 0 01-1.5 0V4.81l-6.22 6.22a.75.75 0 11-1.06-1.06l7.5-7.5z" clipRule="evenodd" />
                </svg>
              </button>
              <textarea
                ref={textareaRef}
                dir="rtl"
                rows={1}
                aria-label="הודעה לצ'אט"
                placeholder="שאל אותי על BuyMe..."
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={loading}
                className="flex-1 resize-none border border-gray-200 rounded-2xl px-4 py-2.5 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:opacity-60 transition"
                style={{ maxHeight: '120px', overflowY: 'auto' }}
              />
            </div>
          </div>
        </div>

        {/* TRAY COLUMN — second in DOM. RTL flex-row puts it on the right visually. */}
        <TrayPanel
          items={tray}
          onClear={handleClearTray}
          mobileOpen={trayOpenMobile}
          onMobileToggle={() => setTrayOpenMobile((v) => !v)}
        />
      </div>

      {/* Profile drawer */}
      {profileOpen && (
        <ProfileDrawer
          user={currentUser}
          onClose={() => setProfileOpen(false)}
          onLogout={() => {
            clearAuth()
            setCurrentUser(null)
            setProfileOpen(false)
            setMessages([WELCOME_MESSAGE(null)])
            setChipStrip([])
            // Clear the tray on a logged-in user's logout — otherwise items
            // from a personal session persist for the next person on a shared
            // device. Anon → anon retention is fine (no identity change).
            setTray([])
            try { localStorage.removeItem(TRAY_KEY) } catch { /* ignore */ }
            // Reset conversational state so the next turn doesn't carry over
            // stale intent (would falsely trigger the topic-change subtitle)
            // or hidden suggestion chips.
            lastIntent.current = null
            userMessageCount.current = 0
            setChipsVisible(true)
            setShowRegPrompt(false)
            setShowRegForm(false)
          }}
        />
      )}
    </div>
  )
}

// --- TrayPanel sub-component ----------------------------------------------

interface TrayPanelProps {
  items: TrayItem[]
  onClear: () => void
  mobileOpen: boolean
  onMobileToggle: () => void
}

function TrayPanel({ items, onClear, mobileOpen, onMobileToggle }: TrayPanelProps) {
  const count = items.length
  return (
    <aside
      className="
        flex-shrink-0 md:flex-[4]
        border-t md:border-t-0 md:border-l border-gray-200
        bg-white
        flex flex-col min-h-0
      "
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 shrink-0">
        <button
          className="text-sm font-medium text-gray-700 flex items-center gap-1 md:cursor-default"
          aria-expanded={mobileOpen}
          aria-controls="tray-items-panel"
          // Desktop: tray is always visible — match-media check prevents the
          // click from polluting localStorage.findme_tray_open. The button
          // remains semantically a button for screen-reader consistency.
          onClick={() => {
            if (typeof window !== 'undefined' && window.matchMedia('(min-width: 768px)').matches) return
            onMobileToggle()
          }}
        >
          <span>🛒</span>
          <span>שמירה זמנית{count > 0 ? ` (${count})` : ''}</span>
          <span className="md:hidden text-xs text-gray-400 ml-1">{mobileOpen ? '▴' : '▾'}</span>
        </button>
        {count > 0 && (
          <button onClick={onClear} className="text-xs text-gray-500 hover:text-red-500">
            🗑️ נקה
          </button>
        )}
      </div>

      {/* Items — always shown on desktop; mobile respects mobileOpen */}
      <div id="tray-items-panel" className={`${mobileOpen ? 'block' : 'hidden'} md:block flex-1 overflow-y-auto px-3 py-3 space-y-3`}>
        {count === 0 ? (
          <p className="text-xs text-gray-400 italic text-center mt-4">
            אין עדיין מועדפים — חיפושים יישמרו כאן
          </p>
        ) : (
          items.map((it, i) => (
            <div key={`${it.type}:${it.id}:${i}`}>
              {it.type === 'product' ? <ResultCard result={it.item} /> : <StoreCard result={it.item} />}
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
