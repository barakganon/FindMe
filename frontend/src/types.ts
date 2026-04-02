export interface SearchFilters {
  online_only: boolean
  max_price: number | null
  min_price?: number | null
  city: string | null
  min_match_score: number
  brand: string | null
  page: number
  page_size: number
  hide_out_of_stock?: boolean
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
  image_url?: string | null
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

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface SessionContext {
  user_lat: number | null
  user_lng: number | null
  location_label: string | null
  voucher_network: string
}

export interface ChatResponse {
  message: string
  intent: 'product_search' | 'store_search' | 'help' | 'clarify'
  product_results: ProductResult[] | null
  store_results: StoreResult[] | null
  needs_location: boolean
  location_prompt: string | null
  voucher_network: string
  search_time_ms: number
  total_available?: number | null
}

// Auth types
export interface User {
  id: string;
  email: string;
  display_name: string | null;
}

export interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
}

export interface UserLocation {
  id: string;
  label: string;
  lat: number;
  lng: number;
  address?: string;
  is_default: boolean;
}

export interface VoucherCard {
  id: string;
  voucher_network: string;
  nickname?: string;
  balance?: number;
  expiry_date?: string;
  is_active: boolean;
}

export interface UserPreferences {
  default_max_price?: string;
  preferred_cities?: string;
  preferred_categories?: string;
  show_online_only?: string;
  default_radius_km?: string;
}

export interface InferredAttribute {
  id: string;
  attribute: string;
  value: string;
  confidence: number;
  source?: string;
  inferred_at: string;
  is_confirmed: boolean;
}

export interface FavoriteStore {
  store_id: string;
  note?: string;
  saved_at: string;
}

export interface SearchHistoryItem {
  id: string;
  message: string;
  intent?: string;
  searched_at: string;
  result_count?: number;
}
