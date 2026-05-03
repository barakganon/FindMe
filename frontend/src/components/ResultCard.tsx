import { useState } from 'react'
import type { ProductResult } from '../types'

interface Props { result: ProductResult }

export function ResultCard({ result }: Props) {
  const storeName = result.store.name_he
  const [imgError, setImgError] = useState(false)
  const inStock = result.availability

  const linkUrl = result.product_url ?? result.store.buyme_url

  const cardClass = inStock
    ? 'bg-white border border-gray-100 rounded-xl shadow-sm p-3 flex flex-col gap-1.5 hover:shadow-md transition-shadow'
    : 'bg-gray-50 border border-gray-200 rounded-xl shadow-sm p-3 flex flex-col gap-1.5 opacity-60'

  return (
    <div className={cardClass}>
      {/* Product image */}
      {result.image_url && !imgError && (
        <img
          src={result.image_url}
          alt={result.canonical_name}
          className={`w-full h-24 object-cover rounded-lg mb-1${inStock ? '' : ' grayscale'}`}
          onError={() => setImgError(true)}
        />
      )}

      {/* Store name */}
      <p className="text-xs text-gray-400">{storeName}</p>

      {/* Product name */}
      <p className="text-sm font-medium text-gray-900 line-clamp-2 leading-snug">
        {result.canonical_name}
      </p>

      {/* Price */}
      {result.price != null ? (
        <span className={`font-semibold text-sm ${inStock ? 'text-green-600' : 'text-gray-500 line-through'}`}>
          ₪{result.price.toLocaleString('he-IL')}
        </span>
      ) : (
        <span className="text-gray-400 text-xs">מחיר לא זמין</span>
      )}

      {/* Availability + meta row */}
      <div className="flex items-center gap-2 text-xs flex-wrap">
        {inStock ? (
          <>
            <span className="text-green-500">●</span>
            <span className="text-gray-400">במלאי</span>
          </>
        ) : (
          <span className="text-red-600 font-semibold bg-red-50 px-2 py-0.5 rounded">אזל המלאי</span>
        )}
        {result.store.city && <span className="text-gray-400">· {result.store.city}</span>}
        {result.store.distance_km != null && (
          <span className="text-gray-400">· {result.store.distance_km.toFixed(1)} ק"מ</span>
        )}
      </div>

      {/* Purchase link */}
      <a
        href={linkUrl || '#'}
        target="_blank"
        rel="noopener noreferrer"
        className={`mt-1 text-xs ${inStock ? 'text-blue-600 hover:underline' : 'text-gray-400 hover:underline'}`}
      >
        {inStock ? 'לרכישה ←' : 'לפרטים ←'}
      </a>
    </div>
  )
}
