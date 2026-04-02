import type { ProductResult } from '../types'

interface Props { result: ProductResult }

export function ResultCard({ result }: Props) {
  const storeName = result.store.name_en ?? result.store.name_he
  const scorePercent = Math.round(result.match_score * 100)

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 flex flex-col gap-2 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start">
        <span className="font-bold text-lg text-gray-800">{storeName}</span>
        {result.availability
          ? <span className="text-green-600 text-sm font-medium">במלאי</span>
          : <span className="text-red-400 text-sm">אזל</span>}
      </div>
      <p className="text-gray-700 text-sm font-medium">{result.canonical_name}</p>
      {result.brand && (
        <p className="text-gray-400 text-xs">{result.brand}</p>
      )}
      {result.price != null && (
        <p className="text-blue-700 font-bold text-xl">
          ₪{result.price.toLocaleString('he-IL')}
        </p>
      )}
      <div className="flex gap-2 text-xs text-gray-400 flex-wrap">
        {result.store.city && <span>📍 {result.store.city}</span>}
        {result.store.is_online && <span>🌐 אונליין</span>}
        {result.store.distance_km != null && (
          <span>📏 {result.store.distance_km} ק"מ</span>
        )}
        <span className="mr-auto text-blue-400">{scorePercent}% התאמה</span>
      </div>
      {result.product_url && (
        <a
          href={result.product_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 text-center py-2 bg-orange-500 text-white rounded-lg text-sm font-medium hover:bg-orange-600 transition-colors"
        >
          לצפייה במוצר
        </a>
      )}
      {result.store.buyme_url && (
        <a
          href={result.store.buyme_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-center py-1.5 border border-orange-300 text-orange-600 rounded-lg text-xs hover:bg-orange-50 transition-colors"
        >
          לחנות BuyMe
        </a>
      )}
    </div>
  )
}
