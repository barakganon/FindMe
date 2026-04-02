import { useState } from 'react'
import { SearchBox } from './components/SearchBox'
import { FilterBar } from './components/FilterBar'
import { ResultCard } from './components/ResultCard'
import { StoreMap } from './components/StoreMap'
import { searchProduct } from './api'
import type { SearchFilters, SearchResponse } from './types'

export default function App() {
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

  const runSearch = async (query: string, updatedFilters: SearchFilters) => {
    setLoading(true)
    setError(null)
    try {
      const data = await searchProduct(query, updatedFilters)
      setResponse(data)
    } catch (e) {
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

      {/* Search */}
      <main className="max-w-5xl mx-auto px-4 py-10">
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

            {/* Pagination controls */}
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
      </main>

      <footer className="text-center text-xs text-gray-300 py-6">
        FindMe — חיפוש חכם לכרטיסי מתנה BuyMe
      </footer>
    </div>
  )
}
