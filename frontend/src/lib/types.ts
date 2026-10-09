export type Mode = "flight" | "train" | "bus";
export interface Offer {
  seller: string; price: number; url: string; fare_class: string; baggage_kg: number | null;
  refundable: boolean; via?: string | null; available: boolean;
}
export interface Trip {
  id: string; mode: Mode; airline: string; airline_code: string; flight_number: string;
  origin: string; destination: string; departure: string; arrival: string | null;
  aircraft: string | null; seats_left: number | null; features: string[];
  origin_terminal: string | null; destination_terminal: string | null; stops: string[];
  logo: string | null; rating: number | null; offers: Offer[];
  duration_min: number | null; min_price: number; seller_count: number; available: boolean;
}
export interface ProviderStatus {
  ok: boolean; ms: number; count: number; error: string | null; stale?: boolean; cached?: boolean;
  /** Seconds since this seller's answer was fetched, when it came from the cache. */
  age?: number | null; refreshing?: boolean;
}
export interface Query {
  mode: Mode; origin: string; destination: string; date: string; adults: number; children: number; infants: number;
  /** Return date for a round trip (YYYY-MM-DD); absent for one-way. */
  ret?: string;
}
export interface SearchResponse {
  query: Query; flights: Trip[]; providers: Record<string, ProviderStatus>;
  /** Streamed searches: sellers still searching, and whether this is the last update. */
  pending?: string[]; done?: boolean;
}
export interface City { code: string; name: string; modes: Mode[] }
export interface PricePoint { ts: string; price: number }
export interface CalendarDay { date: string; min_price: number | null; flights: number | null }
export interface Popular { origin: string; destination: string; origin_name: string; destination_name: string }
export interface Alert {
  id: number; mode: Mode; origin: string; destination: string; date: string; target_price: number; contact: string;
  flight_id: string | null; created: string; triggered_at: string | null; notified_at: string | null; last_price: number | null;
}
