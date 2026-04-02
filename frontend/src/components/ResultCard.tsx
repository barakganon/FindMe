import { useState } from 'react'
import type { ProductResult } from '../types'

interface Props { result: ProductResult }

export function ResultCard({ result }: Props) {
  const storeName = result.store.name_he
  const [imgError, setImgError] = useState(false)

  const linkUrl = result.product_url ?? result.store.buyme_url

  return (
    <div className="bg-white border border-gray-100 rounded-xl shadow-sm p-3 flex flex-col gap-1.5 hover:shadow-md transition-shadow">
      {/* Product image */}
      {result.image_url && !imgError && (
        <img
          src={result.image_url}
          alt={result.canonical_name}
          className="w-full h-24 object-cover rounded-lg mb-1"
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
        <span className="text-green-600 font-semibold text-sm">
          ₪{result.price.toLocaleString('he-IL')}
        </span>
      ) : (
        <span className="text-gray-400 text-xs">מחיר לא זמין</span>
      )}

      {/* Availability + meta row */}
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <span className={result.availability ? 'text-green-500' : 'text-gray-400'}>●</span>
        <span>{result.availability ? 'במלאי' : 'אזל'}</span>
        {result.store.city && <span>· {result.store.city}</span>}
        {result.store.distance_km != null && (
          <span>· {result.store.distance_km.toFixed(1)} ק"מ</span>
        )}
      </div>

      {/* Purchase link */}
      <a
        href={linkUrl || '#'}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 text-blue-600 text-xs hover:underline"
      >
        לרכישה ←
      </a>
    </div>
  )
}
