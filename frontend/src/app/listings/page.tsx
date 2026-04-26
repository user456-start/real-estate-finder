"use client";

import { useEffect, useState, useCallback } from "react";
import type { ListingSummary } from "@/lib/api";
import { getListings } from "@/lib/api";
import ListingCard from "@/components/ListingCard";

const ALL_AREAS = [
  "JLT", "Dubai Marina", "Downtown Dubai", "Business Bay", "DIFC",
  "Palm Jumeirah", "Jumeirah", "Al Barsha", "Deira", "Bur Dubai",
];

export default function ListingsPage() {
  const [listings, setListings] = useState<ListingSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [area, setArea] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [beds, setBeds] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, limit: 18 };
      if (area) params.area = area;
      if (minPrice) params.min_price = Number(minPrice);
      if (maxPrice) params.max_price = Number(maxPrice);
      if (beds) params.beds = Number(beds);
      const res = await getListings(params);
      setListings(res.listings);
      setTotal(res.total);
    } catch { setListings([]); }
    finally { setLoading(false); }
  }, [page, area, minPrice, maxPrice, beds]);

  useEffect(() => { load(); }, [load]);

  const totalPages = Math.ceil(total / 18);

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <div className="bg-white rounded-lg border border-gray-200 p-4 mb-6">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[140px]">
            <label className="block text-xs font-medium text-gray-600 mb-1">Area</label>
            <select value={area} onChange={(e) => { setArea(e.target.value); setPage(1); }} className="w-full border rounded-md px-3 py-2 text-sm bg-white">
              <option value="">All areas</option>
              {ALL_AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div className="w-32">
            <label className="block text-xs font-medium text-gray-600 mb-1">Min price</label>
            <input type="number" value={minPrice} onChange={(e) => { setMinPrice(e.target.value); setPage(1); }} placeholder="40,000" className="w-full border rounded-md px-3 py-2 text-sm" />
          </div>
          <div className="w-32">
            <label className="block text-xs font-medium text-gray-600 mb-1">Max price</label>
            <input type="number" value={maxPrice} onChange={(e) => { setMaxPrice(e.target.value); setPage(1); }} placeholder="120,000" className="w-full border rounded-md px-3 py-2 text-sm" />
          </div>
          <div className="w-24">
            <label className="block text-xs font-medium text-gray-600 mb-1">Beds</label>
            <select value={beds} onChange={(e) => { setBeds(e.target.value); setPage(1); }} className="w-full border rounded-md px-3 py-2 text-sm bg-white">
              <option value="">Any</option>
              <option value="0">Studio</option>
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3+</option>
            </select>
          </div>
          <button onClick={() => { setArea(""); setMinPrice(""); setMaxPrice(""); setBeds(""); setPage(1); }} className="text-sm text-gray-500 hover:text-gray-700 pb-2">
            Clear
          </button>
        </div>
      </div>

      <p className="text-sm text-gray-500 mb-4">{loading ? "Loading..." : `${total.toLocaleString()} listings found`}</p>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => <div key={i} className="animate-pulse bg-white border rounded-lg h-72" />)}
        </div>
      ) : listings.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-lg border">
          <p className="text-gray-500">No listings match your filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {listings.map((l) => <ListingCard key={l.id} listing={l} />)}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-8">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="px-3 py-1.5 text-sm border rounded-md disabled:opacity-40 hover:bg-gray-50">Previous</button>
          <span className="text-sm text-gray-600">Page {page} of {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => setPage(page + 1)} className="px-3 py-1.5 text-sm border rounded-md disabled:opacity-40 hover:bg-gray-50">Next</button>
        </div>
      )}
    </div>
  );
}
