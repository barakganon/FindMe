import React, { useState } from 'react'

interface Props {
  onSearch: (query: string) => void
  loading: boolean
}

export function SearchBox({ onSearch, loading }: Props) {
  const [value, setValue] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (value.trim()) onSearch(value.trim())
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2 w-full max-w-2xl mx-auto">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="הדבק URL של מוצר או שם מוצר..."
        aria-label="הדבק URL של מוצר או שם מוצר"
        className="flex-1 px-4 py-3 text-lg border-2 border-blue-300 rounded-xl focus:outline-none focus:border-blue-500 text-right"
        dir="rtl"
        disabled={loading}
      />
      <button
        type="submit"
        disabled={loading || !value.trim()}
        className="px-6 py-3 bg-blue-600 text-white text-lg font-bold rounded-xl hover:bg-blue-700 disabled:opacity-50 transition-colors"
      >
        {loading ? '...' : 'חפש'}
      </button>
    </form>
  )
}
