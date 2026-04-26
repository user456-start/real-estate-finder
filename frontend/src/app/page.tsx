"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { RankedListing, Preferences } from "@/lib/api";
import { getShortlist, getPreferences } from "@/lib/api";
import ListingCard from "@/components/ListingCard";
import PreferencesForm from "@/components/PreferencesForm";

export default function HomePage() {
  const [shortlist, setShortlist] = useState<RankedListing[]>([]);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [showPrefs, setShowPrefs] = useState(false);

  const loadData = () => {
    setLoading(true);
    Promise.all([getShortlist(), getPreferences()])
      .then(([sl, p]) => { setShortlist(sl); setPrefs(p); })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(loadData, []);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="text-center mb-10">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Find your perfect home in Dubai</h1>
        <p className="text-gray-500 max-w-xl mx-auto">
          AI-powered property matching. We score every listing by price, metro proximity,
          and nearby amenities to surface the best matches for you.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Your preferences</h2>
            {prefs && (
              <p className="text-sm text-gray-500 mt-1">
                {prefs.bedrooms.length > 0 && `${prefs.bedrooms.map(b => b === 0 ? "Studio" : `${b}BR`).join(", ")} | `}
                AED {(prefs.min_price || 0).toLocaleString()} - {(prefs.max_price || 0).toLocaleString()}/yr
                {prefs.areas.length > 0 && ` | ${prefs.areas.slice(0, 4).join(", ")}${prefs.areas.length > 4 ? "..." : ""}`}
              </p>
            )}
          </div>
          <button onClick={() => setShowPrefs(!showPrefs)} className="text-sm text-blue-600 hover:text-blue-700 font-medium">
            {showPrefs ? "Close" : "Edit"}
          </button>
        </div>
        {showPrefs && <PreferencesForm onSaved={() => { setShowPrefs(false); loadData(); }} />}
      </div>

      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Today&apos;s top matches</h2>
            <p className="text-sm text-gray-500">Ranked by price, metro, and mall proximity</p>
          </div>
          <Link href="/listings" className="text-sm text-blue-600 hover:text-blue-700 font-medium">
            View all listings &rarr;
          </Link>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => <div key={i} className="animate-pulse bg-white border rounded-lg h-72" />)}
          </div>
        ) : shortlist.length === 0 ? (
          <div className="text-center py-12 bg-white rounded-lg border">
            <p className="text-gray-500">No listings match your current preferences.</p>
            <button onClick={() => setShowPrefs(true)} className="mt-2 text-sm text-blue-600 hover:text-blue-700">
              Adjust your preferences
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {shortlist.slice(0, 6).map((l) => <ListingCard key={l.id} listing={l} ranked />)}
          </div>
        )}

        {shortlist.length > 6 && (
          <div className="text-center mt-4">
            <Link href="/listings" className="inline-block bg-white border border-gray-300 text-gray-700 text-sm font-medium px-6 py-2.5 rounded-lg hover:bg-gray-50 transition-colors">
              See all {shortlist.length} top matches
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
