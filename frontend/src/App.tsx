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
  const [filters, setFilters] = useState<SearchFilters>({
    online_only: false,
    max_price: null,
    city: null,
    min_match_score: 0.3,
  })

  const handleSearch = async (query: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await searchProduct(query, filters)
      setResponse(data)
    } catch (e) {
      setError('שגיאה בחיפוש. נסה שנית.')
    } finally {
      setLoading(false)
    }
  }

  const activeFilterSummary = [
    filters.online_only ? 'אונליין בלבד' : null,
    filters.max_price != null ? `עד ₪${filters.max_price}` : null,
    filters.city ? `עיר: ${filters.city}` : null,
  ]
    .filter(Boolean)
    .join(' · ')

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
                נמצאו{' '}
                <strong>{response.total}</strong>{' '}
                תוצאות עבור{' '}
                <strong>{response.query_product.extracted_name ?? response.query_product.raw_query}</strong>
                {activeFilterSummary && (
                  <span className="ml-2 text-sm text-blue-600">({activeFilterSummary})</span>
                )}
              </p>
            </div>

            {response.results.some((r) => r.lat != null) && (
              <StoreMap results={response.results} />
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {response.results.map((result, i) => (
                <ResultCard key={i} result={result} />
              ))}
            </div>
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
