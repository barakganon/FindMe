export interface SearchFilters {
  online_only: boolean
  max_price: number | null
  city: string | null
  min_match_score: number
  brand: string | null
  page: number
  page_size: number
}

export interface StoreResult {
  id: string
  name_he: string
  name_en: string | null
  buyme_url: string | null
  buyme_category: string
  address: string | null
  city: string | null
  lat: number | null
  lng: number | null
  distance_km: number | null
  is_online: boolean
  product_count: number
}

export interface StoreSearchRequest {
  query: string
  store_type: 'restaurant' | 'retail' | null
  location: { lat: number; lng: number; radius_km: number } | null
  page: number
  page_size: number
}

export interface StoreSearchResponse {
  stores: StoreResult[]
  total: number
  total_available: number
  page: number
  page_size: number
}

export interface StoreInfo {
  id: string
  name_he: string
  name_en: string | null
  buyme_url: string | null
  is_online: boolean
  city: string | null
  lat: number | null
  lng: number | null
  distance_km: number | null
}

export interface ProductResult {
  product_id: string
  canonical_name: string
  brand: string | null
  category_path: string | null
  store: StoreInfo
  price: number | null
  currency: string
  availability: boolean
  product_url: string | null
  match_score: number
}

export interface QueryProduct {
  raw_query: string
  extracted_name: string | null
  brand: string | null
  estimated_price: number | null
  extraction_success: boolean
}

export interface SearchResponse {
  results: ProductResult[]
  query_product: QueryProduct
  total: number
  total_available: number
  page: number
  page_size: number
  exact_matches: number
  similar_matches: number
  search_time_ms: number
}
