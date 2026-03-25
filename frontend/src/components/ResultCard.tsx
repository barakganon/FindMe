import type { SearchResult } from '../types'

interface Props { result: SearchResult }

export function ResultCard({ result }: Props) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 flex flex-col gap-2 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start">
        <span className="font-bold text-lg text-gray-800">{result.store_name}</span>
        {result.availability
          ? <span className="text-green-600 text-sm font-medium">במלאי</span>
          : <span className="text-red-400 text-sm">אזל</span>}
      </div>
      <p className="text-gray-600 text-sm">{result.product_name}</p>
      {result.price != null && (
        <p className="text-blue-700 font-bold text-xl">
          ₪{result.price.toLocaleString('he-IL')}
        </p>
      )}
      <div className="flex gap-2 text-xs text-gray-400">
        {result.city && <span>📍 {result.city}</span>}
        {result.is_online && <span>🌐 אונליין</span>}
      </div>
      <a
        href={result.product_url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 text-center py-2 bg-orange-500 text-white rounded-lg text-sm font-medium hover:bg-orange-600 transition-colors"
      >
        לצפייה במוצר
      </a>
    </div>
  )
}
