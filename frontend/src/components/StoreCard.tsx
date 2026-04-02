import type { StoreResult } from '../types'

interface Props { result: StoreResult }

function getCategoryBadgeClass(category: string): string {
  const lower = category.toLowerCase()
  if (lower.includes('מסעדה') || lower.includes('אוכל') || lower.includes('food') || lower.includes('restaurant')) {
    return 'bg-orange-50 text-orange-700'
  }
  if (lower.includes('ספא') || lower.includes('יופי') || lower.includes('beauty') || lower.includes('spa')) {
    return 'bg-purple-50 text-purple-700'
  }
  if (
    lower.includes('חנות') ||
    lower.includes('אופנה') ||
    lower.includes('retail') ||
    lower.includes('fashion') ||
    lower.includes('store')
  ) {
    return 'bg-blue-50 text-blue-700'
  }
  return 'bg-gray-100 text-gray-600'
}

const CATEGORY_LABEL: Record<string, string> = {
  restaurant: 'מסעדה',
  retail: 'חנות',
}

export function StoreCard({ result }: Props) {
  const displayName = result.name_en ?? result.name_he
  const categoryLabel = CATEGORY_LABEL[result.buyme_category] ?? result.buyme_category
  const badgeClass = getCategoryBadgeClass(result.buyme_category)

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-3 flex flex-col gap-1.5 hover:shadow-md transition-shadow">
      {/* Name + category badge */}
      <div className="flex justify-between items-start gap-2">
        <span className="font-semibold text-sm text-gray-800 leading-tight truncate overflow-hidden">{displayName}</span>
        <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${badgeClass}`}>
          {categoryLabel}
        </span>
      </div>

      {/* Location details */}
      <div className="flex flex-wrap gap-1.5 text-xs text-gray-400">
        {result.city && <span>📍 {result.city}</span>}
        {result.is_online && <span>🌐 אונליין</span>}
        {result.distance_km != null && (
          <span>· {result.distance_km.toFixed(1)} ק"מ</span>
        )}
      </div>

      {/* Address */}
      {result.address && (
        <p className="text-gray-500 text-xs truncate">{result.address}</p>
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
          className="mt-1 text-blue-600 text-xs hover:underline"
        >
          לחנות ←
        </a>
      )}
    </div>
  )
}
