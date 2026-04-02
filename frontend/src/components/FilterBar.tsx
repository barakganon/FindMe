import { useState } from 'react'
import type { SearchFilters } from '../types'

interface Props {
  filters: SearchFilters
  onChange: (f: SearchFilters) => void
}

export function FilterBar({ filters, onChange }: Props) {
  return (
    <div className="flex flex-wrap gap-3 items-center justify-center mt-4 text-sm" dir="rtl">
      {/* Online only toggle */}
      <label className="flex items-center gap-2 cursor-pointer bg-white border border-gray-200 rounded-lg px-3 py-2 hover:border-blue-400 transition-colors">
        <input
          type="checkbox"
          checked={filters.online_only}
          onChange={(e) => onChange({ ...filters, online_only: e.target.checked })}
          className="accent-blue-600 w-4 h-4"
        />
        <span>חנויות אונליין בלבד</span>
      </label>

      {/* Max price */}
      <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-2">
        <span className="text-gray-500">עד</span>
        <input
          type="number"
          min={0}
          step={50}
          placeholder="מחיר"
          value={filters.max_price ?? ''}
          onChange={(e) => onChange({ ...filters, max_price: e.target.value ? Number(e.target.value) : null })}
          className="w-20 text-left outline-none text-gray-700"
          dir="ltr"
        />
        <span className="text-gray-500">₪</span>
      </div>

      {/* City filter */}
      <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-2">
        <span className="text-gray-500">עיר:</span>
        <input
          type="text"
          placeholder="תל אביב..."
          value={filters.city ?? ''}
          onChange={(e) => onChange({ ...filters, city: e.target.value || null })}
          className="w-24 outline-none text-gray-700 text-right"
          dir="rtl"
        />
      </div>

      {/* Brand filter */}
      <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-2">
        <span className="text-gray-500">מותג:</span>
        <input
          type="text"
          placeholder="למשל: Samsung, Bosch..."
          value={filters.brand ?? ''}
          onChange={(e) => onChange({ ...filters, brand: e.target.value || null })}
          className="w-32 outline-none text-gray-700 text-right"
          dir="rtl"
        />
      </div>

      {/* Clear filters */}
      {(filters.online_only || filters.max_price != null || filters.city || filters.brand) && (
        <button
          onClick={() => onChange({ online_only: false, max_price: null, city: null, brand: null, min_match_score: 0.3, page: filters.page, page_size: filters.page_size })}
          className="text-gray-400 hover:text-red-500 transition-colors px-2"
        >
          ✕ נקה פילטרים
        </button>
      )}
    </div>
  )
}
