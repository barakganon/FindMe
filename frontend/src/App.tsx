import { useState, useRef } from 'react'
import { SearchBox } from './components/SearchBox'
import { FilterBar } from './components/FilterBar'
import { ResultCard } from './components/ResultCard'
import { StoreCard } from './components/StoreCard'
import { StoreMap } from './components/StoreMap'
import { searchProduct, searchStores, geocodeAddress } from './api'
import type {
  SearchFilters,
  SearchResponse,
  StoreSearchResponse,
  StoreResult,
} from './types'

type Tab = 'product' | 'stores'
type LocationMode = 'gps' | 'address'

export default function App() {
  // ── Tab ──────────────────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<Tab>('product')

  // ── Product search state ─────────────────────────────────────────────────
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [currentQuery, setCurrentQuery] = useState<string>('')
  const [filters, setFilters] = useState<SearchFilters>({
    online_only: false,
    max_price: null,
    city: null,
    brand: null,
    min_match_score: 0.3,
    page: 1,
    page_size: 20,
  })

  // ── Store search state ───────────────────────────────────────────────────
  const [storeQuery, setStoreQuery] = useState('')
  const [storeType, setStoreType] = useState<'restaurant' | 'retail' | null>(null)
  const [locationMode, setLocationMode] = useState<LocationMode>('address')
  const [addressInput, setAddressInput] = useState('')
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [locationLabel, setLocationLabel] = useState<string | null>(null)
  const [radius, setRadius] = useState(5)
  const [storeResponse, setStoreResponse] = useState<StoreSearchResponse | null>(null)
  const [storeLoading, setStoreLoading] = useState(false)
  const [storeError, setStoreError] = useState<string | null>(null)
  const [storePage, setStorePage] = useState(1)
  const [geocoding, setGeocoding] = useState(false)
  const addressInputRef = useRef<HTMLInputElement>(null)

  // ── Product search handlers ───────────────────────────────────────────────
  const runSearch = async (query: string, updatedFilters: SearchFilters) => {
    setLoading(true)
    setError(null)
    try {
      const data = await searchProduct(query, updatedFilters)
      setResponse(data)
    } catch {
      setError('שגיאה בחיפוש. נסה שנית.')
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = async (query: string) => {
    const resetFilters = { ...filters, page: 1 }
    setCurrentQuery(query)
    setFilters(resetFilters)
    await runSearch(query, resetFilters)
  }

  const handlePageChange = async (newPage: number) => {
    const updatedFilters = { ...filters, page: newPage }
    setFilters(updatedFilters)
    await runSearch(currentQuery, updatedFilters)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const activeFilterSummary = [
    filters.online_only ? 'אונליין בלבד' : null,
    filters.max_price != null ? `עד ₪${filters.max_price}` : null,
    filters.city ? `עיר: ${filters.city}` : null,
    filters.brand ? `מותג: ${filters.brand}` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const totalPages = response
    ? Math.ceil(response.total_available / response.page_size)
    : 0
  const currentPage = response?.page ?? 1
  const rangeStart = response ? (currentPage - 1) * response.page_size + 1 : 0
  const rangeEnd = response ? rangeStart + response.results.length - 1 : 0

  // ── Store search handlers ─────────────────────────────────────────────────
  const handleUseGPS = () => {
    if (!navigator.geolocation) {
      setStoreError('הדפדפן אינו תומך במיקום GPS')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude })
        setLocationLabel('המיקום שלי')
        setStoreError(null)
      },
      () => setStoreError('לא ניתן לקבל מיקום GPS. אנא הרשה גישה למיקום.')
    )
  }

  const handleGeocodeAddress = async () => {
    const addr = addressInput.trim()
    if (!addr) return
    setGeocoding(true)
    setStoreError(null)
    try {
      const result = await geocodeAddress(addr)
      setUserLocation({ lat: result.lat, lng: result.lng })
      setLocationLabel(result.display_name)
    } catch {
      setStoreError('לא ניתן למצוא את הכתובת. נסה שם מקום אחר.')
    } finally {
      setGeocoding(false)
    }
  }

  const runStoreSearch = async (page: number) => {
    setStoreLoading(true)
    setStoreError(null)
    try {
      const data = await searchStores({
        query: storeQuery,
        store_type: storeType,
        location:
          userLocation != null
            ? { lat: userLocation.lat, lng: userLocation.lng, radius_km: radius }
            : null,
        page,
        page_size: 20,
      })
      setStoreResponse(data)
      setStorePage(page)
    } catch {
      setStoreError('שגיאה בחיפוש חנויות. נסה שנית.')
    } finally {
      setStoreLoading(false)
    }
  }

  const handleStoreSearch = () => {
    setStorePage(1)
    runStoreSearch(1)
  }

  const handleStorePageChange = (newPage: number) => {
    runStoreSearch(newPage)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const storeTotalPages = storeResponse
    ? Math.ceil(storeResponse.total_available / storeResponse.page_size)
    : 0
  const storeLocated = storeResponse?.stores.filter(
    (s): s is StoreResult & { lat: number; lng: number } =>
      s.lat != null && s.lng != null
  ) ?? []

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 to-white" dir="rtl">
      {/* Header */}
      <header className="bg-white shadow-sm py-4 px-6">
        <div className="max-w-5xl mx-auto flex items-center gap-3">
          <div>
            <h1 className="text-2xl font-bold text-blue-700">FindMe 🔍</h1>
            <p className="text-xs text-gray-400">מצא מוצרים בחנויות BuyMe</p>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-10">

        {/* ── Tab switcher ── */}
        <div className="flex justify-center mb-8">
          <div className="inline-flex rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <button
              onClick={() => setActiveTab('product')}
              className={`px-6 py-2.5 text-sm font-medium transition-colors ${
                activeTab === 'product'
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              חיפוש מוצר
            </button>
            <button
              onClick={() => setActiveTab('stores')}
              className={`px-6 py-2.5 text-sm font-medium transition-colors ${
                activeTab === 'stores'
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              חנויות בקרבת מקום
            </button>
          </div>
        </div>

        {/* ══════════════════════════════════════════════════════════════════
            TAB 1 — Product search (existing flow, unchanged)
        ══════════════════════════════════════════════════════════════════ */}
        {activeTab === 'product' && (
          <>
            <div className="text-center mb-8">
              <h2 className="text-3xl font-bold text-gray-800 mb-2">איפה אפשר לקנות את זה עם BuyMe?</h2>
              <p className="text-gray-500">כתוב שם מוצר בעברית/אנגלית, או הדבק URL מ-Amazon, KSP, Zap ועוד</p>
            </div>

            <SearchBox onSearch={handleSearch} loading={loading} />
            <FilterBar filters={filters} onChange={setFilters} />

            {error && (
              <p className="text-center text-red-500 mt-6">{error}</p>
            )}

            {response && (
              <div className="mt-8 space-y-6">
                <div className="text-center">
                  <p className="text-gray-600">
                    {response.total_available > 0 ? (
                      <>
                        נמצאו{' '}
                        <strong>{response.total_available}</strong>{' '}
                        תוצאות עבור{' '}
                        <strong>{response.query_product.extracted_name ?? response.query_product.raw_query}</strong>
                        {response.total_available > response.page_size && (
                          <span className="text-sm text-gray-400 mr-2">
                            (מציג {rangeStart}–{rangeEnd})
                          </span>
                        )}
                      </>
                    ) : (
                      <>
                        לא נמצאו תוצאות עבור{' '}
                        <strong>{response.query_product.extracted_name ?? response.query_product.raw_query}</strong>
                      </>
                    )}
                    {activeFilterSummary && (
                      <span className="mr-2 text-sm text-blue-600">({activeFilterSummary})</span>
                    )}
                  </p>
                </div>

                {response.results.some((r) => r.store.lat != null) && (
                  <StoreMap results={response.results} />
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {response.results.map((result, i) => (
                    <ResultCard key={i} result={result} />
                  ))}
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-center gap-4 pt-4">
                    <button
                      onClick={() => handlePageChange(currentPage + 1)}
                      disabled={currentPage >= totalPages || loading}
                      className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
                    >
                      הבא &rarr;
                    </button>

                    <span className="text-sm text-gray-600">
                      עמוד <strong>{currentPage}</strong> מתוך <strong>{totalPages}</strong>
                    </span>

                    <button
                      onClick={() => handlePageChange(currentPage - 1)}
                      disabled={currentPage <= 1 || loading}
                      className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
                    >
                      &larr; הקודם
                    </button>
                  </div>
                )}
              </div>
            )}

            {response && response.results.length === 0 && (
              <div className="text-center mt-10 text-gray-400">
                <p className="text-5xl mb-4">🔍</p>
                <p>לא נמצאו תוצאות. נסה שם מוצר אחר.</p>
              </div>
            )}
          </>
        )}

        {/* ══════════════════════════════════════════════════════════════════
            TAB 2 — Nearby store search (new)
        ══════════════════════════════════════════════════════════════════ */}
        {activeTab === 'stores' && (
          <>
            <div className="text-center mb-8">
              <h2 className="text-3xl font-bold text-gray-800 mb-2">חנויות BuyMe בקרבת מקום</h2>
              <p className="text-gray-500">מצא מסעדות, חנויות וספא שמקבלים BuyMe ליד הכתובת שלך</p>
            </div>

            {/* Search controls card */}
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 space-y-5">

              {/* Store name search */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">שם חנות / מסעדה</label>
                <input
                  type="text"
                  placeholder="חפש שם חנות / מסעדה..."
                  value={storeQuery}
                  onChange={(e) => setStoreQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleStoreSearch()}
                  className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 transition"
                  dir="rtl"
                />
              </div>

              {/* Store type selector */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">סוג עסק</label>
                <div className="flex gap-2 flex-wrap">
                  {(
                    [
                      { value: null,         label: 'הכל' },
                      { value: 'restaurant', label: 'מסעדות' },
                      { value: 'retail',     label: 'חנויות' },
                    ] as const
                  ).map(({ value, label }) => (
                    <button
                      key={String(value)}
                      onClick={() => setStoreType(value)}
                      className={`px-4 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                        storeType === value
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'bg-white text-gray-600 border-gray-200 hover:border-blue-400'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Location section */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">מיקום</label>

                {/* Mode toggle */}
                <div className="flex gap-3 mb-3">
                  <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-600">
                    <input
                      type="radio"
                      name="locationMode"
                      checked={locationMode === 'address'}
                      onChange={() => setLocationMode('address')}
                      className="accent-blue-600"
                    />
                    כתובת / שם מקום
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-600">
                    <input
                      type="radio"
                      name="locationMode"
                      checked={locationMode === 'gps'}
                      onChange={() => setLocationMode('gps')}
                      className="accent-blue-600"
                    />
                    📍 מיקום שלי (GPS)
                  </label>
                </div>

                {locationMode === 'address' ? (
                  <div className="flex gap-2">
                    <input
                      ref={addressInputRef}
                      type="text"
                      placeholder='למשל: "יקב טוליפ", "תל אביב"...'
                      value={addressInput}
                      onChange={(e) => setAddressInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleGeocodeAddress()}
                      className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 transition"
                      dir="rtl"
                    />
                    <button
                      onClick={handleGeocodeAddress}
                      disabled={geocoding || !addressInput.trim()}
                      className="px-4 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors whitespace-nowrap"
                    >
                      {geocoding ? 'מחפש...' : 'חפש'}
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={handleUseGPS}
                    className="px-4 py-2.5 bg-green-600 text-white rounded-xl text-sm font-medium hover:bg-green-700 transition-colors"
                  >
                    📍 השתמש במיקום שלי
                  </button>
                )}

                {/* Location confirmation */}
                {userLocation && locationLabel && (
                  <p className="mt-2 text-xs text-green-600 flex items-center gap-1">
                    <span>✓</span>
                    <span>{locationLabel}</span>
                    <button
                      onClick={() => { setUserLocation(null); setLocationLabel(null) }}
                      className="mr-1 text-gray-400 hover:text-red-500 transition-colors"
                      aria-label="נקה מיקום"
                    >
                      ✕
                    </button>
                  </p>
                )}
              </div>

              {/* Radius slider */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  רדיוס: <strong>{radius} ק״מ</strong>
                </label>
                <input
                  type="range"
                  min={1}
                  max={50}
                  step={1}
                  value={radius}
                  onChange={(e) => setRadius(Number(e.target.value))}
                  className="w-full accent-blue-600"
                  dir="ltr"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                  <span>1 ק״מ</span>
                  <span>50 ק״מ</span>
                </div>
              </div>

              {/* Search button */}
              <button
                onClick={handleStoreSearch}
                disabled={storeLoading}
                className="w-full py-3 bg-blue-600 text-white rounded-xl font-semibold text-base hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {storeLoading ? 'מחפש...' : 'חפש חנויות'}
              </button>
            </div>

            {/* Error */}
            {storeError && (
              <p className="text-center text-red-500 mt-6">{storeError}</p>
            )}

            {/* Results */}
            {storeResponse && (
              <div className="mt-8 space-y-6">
                {/* Summary */}
                <div className="text-center">
                  <p className="text-gray-600">
                    {storeResponse.total_available > 0 ? (
                      <>
                        נמצאו <strong>{storeResponse.total_available}</strong> חנויות
                        {storeResponse.total_available > storeResponse.page_size && (
                          <span className="text-sm text-gray-400 mr-2">
                            (מציג עמוד {storePage} מתוך {storeTotalPages})
                          </span>
                        )}
                      </>
                    ) : (
                      'לא נמצאו חנויות. נסה חיפוש אחר.'
                    )}
                  </p>
                </div>

                {/* Map */}
                {storeLocated.length > 0 && (
                  <StoreMap results={storeResponse.stores} mode="store" />
                )}

                {/* Store cards grid */}
                {storeResponse.stores.length > 0 && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {storeResponse.stores.map((store, i) => (
                      <StoreCard key={store.id ?? i} result={store} />
                    ))}
                  </div>
                )}

                {/* Pagination */}
                {storeTotalPages > 1 && (
                  <div className="flex items-center justify-center gap-4 pt-4">
                    <button
                      onClick={() => handleStorePageChange(storePage + 1)}
                      disabled={storePage >= storeTotalPages || storeLoading}
                      className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
                    >
                      הבא &rarr;
                    </button>

                    <span className="text-sm text-gray-600">
                      עמוד <strong>{storePage}</strong> מתוך <strong>{storeTotalPages}</strong>
                    </span>

                    <button
                      onClick={() => handleStorePageChange(storePage - 1)}
                      disabled={storePage <= 1 || storeLoading}
                      className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
                    >
                      &larr; הקודם
                    </button>
                  </div>
                )}

                {storeResponse.stores.length === 0 && (
                  <div className="text-center mt-10 text-gray-400">
                    <p className="text-5xl mb-4">🗺️</p>
                    <p>לא נמצאו חנויות. נסה לשנות את הפילטרים.</p>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>

      <footer className="text-center text-xs text-gray-300 py-6">
        FindMe — חיפוש חכם לכרטיסי מתנה BuyMe
      </footer>
    </div>
  )
}
