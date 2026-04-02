import { useState, useRef, useEffect } from 'react'
import { sendChatMessage, getMe, register, importSession } from '../api'
import type { ChatMessage, ChatResponse, SessionContext, ProductResult, StoreResult, User } from '../types'
import { getSavedToken, saveAuth, clearAuth, isRegistrationDismissed, dismissRegistration } from '../store/auth'
import { ResultCard } from './ResultCard'
import { StoreCard } from './StoreCard'
import { StoreMap } from './StoreMap'
import ProfileDrawer from './ProfileDrawer'

interface Props {
  sessionContext: SessionContext | null
  onLocationUpdate: (ctx: SessionContext) => void
}

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  response?: ChatResponse
}

const WELCOME_MESSAGE = (name?: string | null): ChatEntry => ({
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

export function ChatInterface({ sessionContext, onLocationUpdate }: Props) {
  const [currentUser, setCurrentUser] = useState<User | null>(null)
  const [messages, setMessages] = useState<ChatEntry[]>([WELCOME_MESSAGE(null)])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [chipsVisible, setChipsVisible] = useState(true)
  const [lastMessage, setLastMessage] = useState<string>('')
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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

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
        if (resendMessage) {
          sendMessage(resendMessage, updated)
        }
      },
      () => {
        // user denied — silently ignore
      }
    )
  }

  const sendMessage = async (text: string, overrideSession?: SessionContext) => {
    if (!text.trim() || loading) return

    const session = overrideSession ?? currentSession

    const history: ChatMessage[] = messages.slice(-10).map((m) => ({
      role: m.role,
      content: m.content,
    }))

    const userEntry: ChatEntry = { role: 'user', content: text }
    setMessages((prev) => [...prev, userEntry])
    setLastMessage(text)
    setLoading(true)
    setChipsVisible(false)

    // Increment message count and show registration prompt after 3rd message
    userMessageCount.current += 1
    if (userMessageCount.current === 3 && !currentUser && !isRegistrationDismissed()) {
      setShowRegPrompt(true)
    }

    try {
      const chatResponse = await sendChatMessage(text, history, session)
      const assistantEntry: ChatEntry = {
        role: 'assistant',
        content: chatResponse.message,
        response: chatResponse,
      }
      setMessages((prev) => [...prev, assistantEntry])
    } catch {
      const errorEntry: ChatEntry = {
        role: 'assistant',
        content: 'מצטער, אירעה שגיאה בעיבוד הבקשה שלך. נסה שנית.',
      }
      setMessages((prev) => [...prev, errorEntry])
    } finally {
      setLoading(false)
      textareaRef.current?.focus()
    }
  }

  const handleSend = () => {
    const text = inputValue.trim()
    if (!text || loading) return
    setInputValue('')
    sendMessage(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleChipClick = (chip: string) => {
    setInputValue('')
    sendMessage(chip)
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
          .filter(m => m.role !== 'assistant' || !m.response)
          .map(m => ({ role: m.role, content: m.content })),
        sessionContext as Record<string, unknown> | null
      ).catch(() => {})
      setShowRegPrompt(false)
      setShowRegForm(false)
    } catch (err: unknown) {
      setRegError(err instanceof Error ? err.message : 'שגיאה ברישום')
    }
  }

  return (
    <div
      className="flex flex-col h-screen bg-gray-50"
      dir="rtl"
      lang="he"
      style={{ fontFamily: "-apple-system, 'Segoe UI', sans-serif" }}
    >
      {/* Fixed header (56px) */}
      <header className="bg-white border-b border-gray-100 shadow-sm flex items-center justify-between px-4 shrink-0" style={{ height: '56px' }}>
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-blue-600">🔍 FindMe</span>
          <span className="text-gray-400 text-sm hidden sm:inline">חיפוש חכם לכרטיסי BuyMe</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="bg-blue-600 text-white text-xs font-medium px-2 py-1 rounded-full">
            BuyMe ✓
          </span>
          {/* Avatar / profile button */}
          <button
            onClick={() => setProfileOpen(true)}
            className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white ${
              currentUser ? 'bg-blue-600' : 'bg-gray-300'
            }`}
            title={currentUser ? currentUser.display_name || currentUser.email : 'התחבר'}
          >
            {currentUser
              ? (currentUser.display_name || currentUser.email)[0].toUpperCase()
              : '👤'
            }
          </button>
        </div>
      </header>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.map((msg, index) => (
          <div
            key={index}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`flex flex-col gap-2 ${
                msg.role === 'user'
                  ? 'items-end ml-auto max-w-[80%]'
                  : 'items-start mr-auto max-w-[85%]'
              }`}
            >
              {/* Text bubble */}
              <div
                className={`px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white rounded-2xl rounded-tr-sm'
                    : 'bg-white border border-gray-100 shadow-sm text-gray-800 rounded-2xl rounded-tl-sm'
                }`}
              >
                {msg.content}

                {/* GPS prompt button — inline inside assistant bubble */}
                {msg.role === 'assistant' && msg.response?.needs_location && (
                  <div className="mt-3">
                    {currentSession.user_lat != null ? (
                      <span className="text-xs text-green-700 flex items-center gap-1">
                        <span>✓</span>
                        <span>מיקום התקבל — שולח שוב...</span>
                      </span>
                    ) : (
                      <button
                        onClick={() => requestGPS(lastMessage)}
                        className="inline-flex items-center gap-1 bg-blue-600 text-white text-xs font-medium px-3 py-1.5 rounded-full hover:bg-blue-700 transition-colors"
                      >
                        <span>📍</span>
                        <span>שתף מיקום</span>
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* Search time */}
              {msg.role === 'assistant' && msg.response && msg.response.search_time_ms > 0 && (
                <span className="text-xs text-gray-400 px-1">
                  נמצא תוך {Math.round(msg.response.search_time_ms)} ms
                </span>
              )}

              {/* Product results grid */}
              {msg.role === 'assistant' &&
                msg.response?.product_results &&
                msg.response.product_results.length > 0 && (
                  <div className="w-full space-y-3">
                    <div className="flex overflow-x-auto gap-3 pb-2 sm:grid sm:grid-cols-3 sm:overflow-x-visible">
                      {msg.response.product_results.slice(0, 6).map((result: ProductResult, i: number) => (
                        <div key={i} className="shrink-0 w-48 sm:w-auto">
                          <ResultCard result={result} />
                        </div>
                      ))}
                    </div>
                    {(() => {
                      const totalAvailable = msg.response.total_available ?? msg.response.product_results.length
                      return totalAvailable > 6 ? (
                        <p className="text-xs text-gray-400 text-center mt-1">
                          ועוד {totalAvailable - 6} תוצאות נוספות
                        </p>
                      ) : null
                    })()}
                    {msg.response.product_results.some((r: ProductResult) => r.store.lat != null) && (
                      <div className="rounded-xl overflow-hidden" style={{ height: '220px' }}>
                        <StoreMap results={msg.response.product_results} mode="product" />
                      </div>
                    )}
                  </div>
                )}

              {/* Store results grid */}
              {msg.role === 'assistant' &&
                msg.response?.store_results &&
                msg.response.store_results.length > 0 && (
                  <div className="w-full space-y-3">
                    <div className="flex overflow-x-auto gap-3 pb-2 sm:grid sm:grid-cols-3 sm:overflow-x-visible">
                      {msg.response.store_results.slice(0, 6).map((store: StoreResult, i: number) => (
                        <div key={store.id ?? i} className="shrink-0 w-48 sm:w-auto">
                          <StoreCard result={store} />
                        </div>
                      ))}
                    </div>
                    {msg.response.store_results.length > 6 && (
                      <p className="text-xs text-blue-600 text-center">
                        ועוד {msg.response.store_results.length - 6} חנויות
                      </p>
                    )}
                    {msg.response.store_results.some((s: StoreResult) => s.lat != null) && (
                      <div className="rounded-xl overflow-hidden" style={{ height: '220px' }}>
                        <StoreMap results={msg.response.store_results} mode="store" />
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
                  <button
                    onClick={() => setShowRegForm(true)}
                    className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded-full"
                  >
                    צור חשבון
                  </button>
                  <button
                    onClick={() => { setShowRegPrompt(false); dismissRegistration(); }}
                    className="px-3 py-1.5 bg-gray-100 text-gray-600 text-xs rounded-full"
                  >
                    המשך בלי חשבון
                  </button>
                </div>
              ) : (
                <form onSubmit={handleRegisterSubmit} className="space-y-2">
                  <input
                    value={regName}
                    onChange={e => setRegName(e.target.value)}
                    placeholder="שם (אופציונלי)"
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 text-right"
                    dir="rtl"
                  />
                  <input
                    required
                    type="email"
                    value={regEmail}
                    onChange={e => setRegEmail(e.target.value)}
                    placeholder="אימייל"
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 text-right"
                    dir="rtl"
                  />
                  <input
                    required
                    type="password"
                    value={regPassword}
                    onChange={e => setRegPassword(e.target.value)}
                    placeholder="סיסמה"
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 text-right"
                    dir="rtl"
                  />
                  {regError && <p className="text-red-500 text-xs text-right">{regError}</p>}
                  <button
                    type="submit"
                    className="w-full py-1.5 bg-blue-600 text-white text-sm rounded-lg"
                  >
                    הירשם
                  </button>
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

        {/* Loading indicator */}
        {loading && (
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

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>

      {/* Location status bar */}
      {currentSession.location_label && (
        <div className="px-4 py-1.5 bg-green-50 border-t border-green-100 flex items-center justify-between text-xs text-green-700 shrink-0">
          <span>📍 {currentSession.location_label}</span>
          <button
            onClick={() =>
              onLocationUpdate({
                ...currentSession,
                user_lat: null,
                user_lng: null,
                location_label: null,
              })
            }
            className="text-gray-400 hover:text-red-500 transition-colors mr-2"
            aria-label="נקה מיקום"
          >
            ✕
          </button>
        </div>
      )}

      {/* Fixed input bar (64px) */}
      <div className="bg-white border-t border-gray-200 shadow-[0_-2px_8px_rgba(0,0,0,0.06)] px-4 py-3 shrink-0" style={{ minHeight: '64px' }}>
        <div className="flex items-center gap-2 max-w-3xl mx-auto">
          <button
            onClick={handleSend}
            disabled={loading || !inputValue.trim()}
            className="shrink-0 flex items-center justify-center w-10 h-10 bg-blue-600 text-white rounded-full hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            aria-label="שלח"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="currentColor"
              className="w-5 h-5"
            >
              <path
                fillRule="evenodd"
                d="M11.47 2.47a.75.75 0 011.06 0l7.5 7.5a.75.75 0 11-1.06 1.06l-6.22-6.22V21a.75.75 0 01-1.5 0V4.81l-6.22 6.22a.75.75 0 11-1.06-1.06l7.5-7.5z"
                clipRule="evenodd"
              />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            dir="rtl"
            rows={1}
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

      {/* Profile Drawer */}
      {profileOpen && (
        <ProfileDrawer
          user={currentUser}
          onClose={() => setProfileOpen(false)}
          onLogout={() => {
            clearAuth()
            setCurrentUser(null)
            setProfileOpen(false)
            setMessages([WELCOME_MESSAGE(null)])
          }}
        />
      )}
    </div>
  )
}
