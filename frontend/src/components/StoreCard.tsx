import type { StoreResult } from '../types'

interface Props { result: StoreResult }

const CATEGORY_LABEL: Record<string, string> = {
  restaurant: 'מסעדה',
  retail: 'חנות',
}

export function StoreCard({ result }: Props) {
  const displayName = result.name_en ?? result.name_he
  const categoryLabel = CATEGORY_LABEL[result.buyme_category] ?? result.buyme_category

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 flex flex-col gap-2 hover:shadow-md transition-shadow">
      {/* Name + category badge */}
      <div className="flex justify-between items-start gap-2">
        <span className="font-bold text-lg text-gray-800 leading-tight">{displayName}</span>
        <span className="shrink-0 bg-orange-100 text-orange-700 text-xs font-medium px-2 py-0.5 rounded-full">
          {categoryLabel}
        </span>
      </div>

      {/* Location details */}
      <div className="flex flex-wrap gap-2 text-xs text-gray-400">
        {result.city && (
          <span>📍 {result.city}</span>
        )}
        {result.is_online && (
          <span>🌐 אונליין</span>
        )}
        {result.distance_km != null && (
          <span>📏 {result.distance_km.toFixed(1)} ק״מ</span>
        )}
      </div>

      {/* Address */}
      {result.address && (
        <p className="text-gray-500 text-xs">{result.address}</p>
      )}

      {/* Product count */}
      {result.product_count > 0 && (
        <p className="text-gray-400 text-xs">
          {result.product_count.toLocaleString('he-IL')} מוצרים
        </p>
      )}

      {/* BuyMe link */}
      {result.buyme_url && (
        <a
          href={result.buyme_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 text-center py-2 border border-orange-300 text-orange-600 rounded-lg text-sm font-medium hover:bg-orange-50 transition-colors"
        >
          BuyMe &larr;
        </a>
      )}
    </div>
  )
}
