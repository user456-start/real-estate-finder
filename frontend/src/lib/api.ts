const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ── Types ───────────────────────────────────────────────────────────────────

export interface ListingSummary {
  id: string;
  title: string;
  price_aed: number | null;
  beds: number | null;
  baths: number | null;
  size_sqft: number | null;
  area_name: string | null;
  url: string;
  lat: number | null;
  lon: number | null;
  platform_name: string | null;
  fetched_at: string | null;
  image_url: string | null;
}

export interface ListingsResponse {
  listings: ListingSummary[];
  total: number;
  page: number;
  limit: number;
}

export interface POISummary {
  name: string;
  type: string;
  lat: number;
  lon: number;
  distance_min?: number;
}

export interface ListingDetail extends ListingSummary {
  description: string | null;
  image_url: string | null;
  area_blurb: string | null;
  nearby_pois: POISummary[];
}

export interface RankedListing extends ListingSummary {
  score: number;
  score_value: number;
  score_location: number;
  metro_name: string;
  metro_min: number;
  mall_name: string;
  mall_min: number;
}

export interface Preferences {
  min_price: number | null;
  max_price: number | null;
  min_beds: number | null;
  bedrooms: number[];
  min_bathrooms: number | null;
  furnished: number | null;
  is_rental: boolean;
  areas: string[];
  extra_criteria: Record<string, unknown> | null;
}

export interface ChatResponse {
  reply: string;
  thread_id: string;
}

// ── API calls ───────────────────────────────────────────────────────────────

export function getListings(params: Record<string, string | number>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  return fetchJSON<ListingsResponse>(`/api/listings?${qs}`);
}

export function getShortlist() {
  return fetchJSON<RankedListing[]>("/api/listings/shortlist");
}

export function getListing(id: string) {
  return fetchJSON<ListingDetail>(`/api/listings/${id}`);
}

export function getSimilar(id: string) {
  return fetchJSON<ListingSummary[]>(`/api/listings/${id}/similar`);
}

export function getPreferences() {
  return fetchJSON<Preferences>("/api/preferences");
}

export function updatePreferences(data: Partial<Preferences>) {
  return fetchJSON<Preferences>("/api/preferences", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function getPois(type?: string) {
  const qs = type ? `?type=${type}` : "";
  return fetchJSON<POISummary[]>(`/api/pois${qs}`);
}

export function sendChatMessage(propertyId: string, message: string, threadId?: string) {
  return fetchJSON<ChatResponse>("/chat/message", {
    method: "POST",
    body: JSON.stringify({
      property_id: propertyId,
      message,
      thread_id: threadId,
    }),
  });
}
