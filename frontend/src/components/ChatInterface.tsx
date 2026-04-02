import { useState, useRef, useEffect } from 'react'
import { sendChatMessage } from '../api'
import type { ChatMessage, ChatResponse, SessionContext, ProductResult, StoreResult } from '../types'
import { ResultCard } from './ResultCard'
import { StoreCard } from './StoreCard'
import { StoreMap } from './StoreMap'

// Extended message type that carries the full API response for result rendering
interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  response?: ChatResponse
}

const WELCOME_MESSAGE: ChatEntry = {
  role: 'assistant',
  content: 'שלום! 👋 אני עוזר ה-BuyMe שלך. אפשר לשאול אותי על מוצרים, מסעדות, חנויות, או כל דבר אחר שאפשר לקנות עם כרטיס ה-BuyMe שלך.',
}

const INITIAL_SESSION: SessionContext = {
  user_lat: null,
  user_lng: null,
  location_label: null,
  voucher_network: 'buyme',
}

export function ChatInterface() {
  const [messages, setMessages] = useState<ChatEntry[]>([WELCOME_MESSAGE])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionContext, setSessionContext] = useState<SessionContext>(INITIAL_SESSION)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const requestGPS = () => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setSessionContext((prev) => ({
          ...prev,
          user_lat: pos.coords.latitude,
          user_lng: pos.coords.longitude,
          location_label: 'המיקום שלי',
        }))
      },
      () => {
        // silently ignore — user denied
      }
    )
  }

  const handleSend = async () => {
    const text = inputValue.trim()
    if (!text || loading) return

    // Build history from last 10 messages (excluding the current user turn)
    const history: ChatMessage[] = messages.slice(-10).map((m) => ({
      role: m.role,
      content: m.content,
    }))

    // Append user message
    const userEntry: ChatEntry = { role: 'user', content: text }
    setMessages((prev) => [...prev, userEntry])
    setInputValue('')
    setLoading(true)

    try {
      const chatResponse = await sendChatMessage(text, history, sessionContext)
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
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-200px)] min-h-[500px]" dir="rtl">

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.map((msg, index) => (
          <div
            key={index}
            className={`flex ${msg.role === 'user' ? 'justify-start' : 'justify-end'}`}
          >
            <div className={`max-w-[85%] flex flex-col gap-2 ${msg.role === 'user' ? 'items-start' : 'items-end'}`}>

              {/* Bubble */}
              <div
                className={`px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                  msg.role === 'user'
                    ? 'bg-blue-500 text-white rounded-tl-2xl rounded-b-2xl'
                    : 'bg-gray-100 text-gray-800 rounded-tr-2xl rounded-b-2xl'
                }`}
              >
                {msg.content}

                {/* GPS prompt button — inline inside assistant bubble */}
                {msg.role === 'assistant' && msg.response?.needs_location && (
                  <div className="mt-2">
                    <button
                      onClick={requestGPS}
                      className="inline-flex items-center gap-1 bg-green-500 text-white text-xs font-medium px-3 py-1.5 rounded-full hover:bg-green-600 transition-colors"
                    >
                      <span>📍</span>
                      <span>שתף מיקום</span>
                    </button>
                    {sessionContext.user_lat != null && (
                      <span className="mr-2 text-xs text-green-700">מיקום התקבל</span>
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

              {/* Product results */}
              {msg.role === 'assistant' &&
                msg.response?.product_results &&
                msg.response.product_results.length > 0 && (
                  <div className="w-full space-y-3">
                    {/* Map for product results that have coordinates */}
                    {msg.response.product_results.some((r: ProductResult) => r.store.lat != null) && (
                      <StoreMap results={msg.response.product_results} mode="product" />
                    )}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {msg.response.product_results.map((result: ProductResult, i: number) => (
                        <ResultCard key={i} result={result} />
                      ))}
                    </div>
                  </div>
                )}

              {/* Store results */}
              {msg.role === 'assistant' &&
                msg.response?.store_results &&
                msg.response.store_results.length > 0 && (
                  <div className="w-full space-y-3">
                    {/* Map for store results that have coordinates */}
                    {msg.response.store_results.some((s: StoreResult) => s.lat != null) && (
                      <StoreMap results={msg.response.store_results} mode="store" />
                    )}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {msg.response.store_results.map((store: StoreResult, i: number) => (
                        <StoreCard key={store.id ?? i} result={store} />
                      ))}
                    </div>
                  </div>
                )}

            </div>
          </div>
        ))}

        {/* Loading indicator — animated "..." bubble */}
        {loading && (
          <div className="flex justify-end">
            <div className="bg-gray-100 text-gray-500 rounded-tr-2xl rounded-b-2xl px-5 py-3 text-sm">
              <span className="inline-flex gap-1">
                <span className="animate-bounce" style={{ animationDelay: '0ms' }}>•</span>
                <span className="animate-bounce" style={{ animationDelay: '150ms' }}>•</span>
                <span className="animate-bounce" style={{ animationDelay: '300ms' }}>•</span>
              </span>
            </div>
          </div>
        )}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>

      {/* Location status bar */}
      {sessionContext.location_label && (
        <div className="px-4 py-1.5 bg-green-50 border-t border-green-100 flex items-center justify-between text-xs text-green-700">
          <span>📍 {sessionContext.location_label}</span>
          <button
            onClick={() =>
              setSessionContext((prev) => ({
                ...prev,
                user_lat: null,
                user_lng: null,
                location_label: null,
              }))
            }
            className="text-gray-400 hover:text-red-500 transition-colors mr-2"
            aria-label="נקה מיקום"
          >
            ✕
          </button>
        </div>
      )}

      {/* Input area */}
      <div className="bg-white border-t border-gray-200 shadow-[0_-2px_8px_rgba(0,0,0,0.06)] px-4 py-3">
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
              className="w-5 h-5 rotate-180"
            >
              <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
            </svg>
          </button>
          <input
            ref={inputRef}
            type="text"
            dir="rtl"
            placeholder="שאל אותי הכל על BuyMe..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            className="flex-1 border border-gray-200 rounded-full px-4 py-2.5 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:opacity-60 transition"
          />
        </div>
      </div>
    </div>
  )
}
