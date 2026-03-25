export interface SearchFilters {
  online_only: boolean
  max_price: number | null
  city: string | null
  min_match_score: number
}

export interface SearchResult {
  store_name: string
  store_id: string
  product_name: string
  price: number | null
  currency: string
  availability: boolean
  product_url: string
  store_url: string | null
  city: string | null
  is_online: boolean
  lat: number | null
  lng: number | null
  similarity_score: number
}

export interface QueryProduct {
  raw_query: string
  extracted_name: string | null
  brand: string | null
  estimated_price: number | null
  extraction_success: boolean
}

export interface SearchResponse {
  results: SearchResult[]
  query_product: QueryProduct
  total: number
  exact_matches: number
  similar_matches: number
  search_time_ms: number
}

export interface Store {
  id: string
  name_he: string
  buyme_category: string
  is_online: boolean
  city: string | null
  store_url: string | null
}
