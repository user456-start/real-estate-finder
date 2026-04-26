"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import type { ListingDetail, ListingSummary } from "@/lib/api";
import { getListing, getSimilar } from "@/lib/api";
import PropertyChat from "@/components/PropertyChat";
import PropertyMap from "@/components/PropertyMap";
import ListingCard from "@/components/ListingCard";

export default function PropertyPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = params.id as string;
  const chatMode = searchParams.get("chat") === "1";

  const [listing, setListing] = useState<ListingDetail | null>(null);
  const [similar, setSimilar] = useState<ListingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"details" | "chat">(chatMode ? "chat" : "details");

  useEffect(() => {
    setLoading(true);
    Promise.all([getListing(id), getSimilar(id)])
      .then(([l, s]) => { setListing(l); setSimilar(s); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-gray-200 rounded w-2/3" />
          <div className="h-80 bg-gray-200 rounded" />
          <div className="h-48 bg-gray-200 rounded" />
        </div>
      </div>
    );
  }

  if (!listing) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-16 text-center">
        <p className="text-gray-500">Listing not found.</p>
        <Link href="/listings" className="text-sm text-blue-600 mt-2 inline-block">Back to listings</Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      {/* Breadcrumb */}
      <div className="text-sm text-gray-500 mb-4">
        <Link href="/listings" className="hover:text-blue-600">Listings</Link>
        {" / "}
        <span className="text-gray-900">{listing.area_name}</span>
      </div>

      {/* Desktop 2-col, mobile stacked */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left: property info */}
        <div className="lg:col-span-3 space-y-6">
          {/* Title + price */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-bold text-gray-900">{listing.title}</h1>
                <p className="text-sm text-gray-500 mt-1">{listing.area_name}</p>
              </div>
              {listing.platform_name && (
                <span className="text-xs text-gray-400 bg-gray-50 px-2 py-1 rounded shrink-0">{listing.platform_name}</span>
              )}
            </div>

            <p className="text-2xl font-bold text-blue-700 mt-3">
              AED {listing.price_aed?.toLocaleString() ?? "N/A"}
              <span className="text-sm font-normal text-gray-500"> /year</span>
            </p>

            <div className="flex flex-wrap gap-4 mt-4 text-sm text-gray-700">
              {listing.beds != null && <span>{listing.beds} bed{listing.beds !== 1 ? "s" : ""}</span>}
              {listing.baths != null && <span>{listing.baths} bath{listing.baths !== 1 ? "s" : ""}</span>}
              {listing.size_sqft != null && <span>{listing.size_sqft.toLocaleString()} sqft</span>}
            </div>

            <a href={listing.url} target="_blank" rel="noopener noreferrer" className="inline-block mt-4 text-sm text-blue-600 hover:text-blue-700 font-medium">
              View on {listing.platform_name || "portal"} &rarr;
            </a>
          </div>

          {/* Nearby POIs */}
          {listing.nearby_pois.length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h2 className="text-sm font-semibold text-gray-900 mb-3">Nearby amenities</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {listing.nearby_pois.map((poi) => (
                  <div key={poi.name} className="flex items-center justify-between text-sm py-1.5 px-2 rounded bg-gray-50">
                    <span className="text-gray-700">
                      <span className={`inline-block w-2 h-2 rounded-full mr-2 ${poi.type === "metro" ? "bg-rose-500" : poi.type === "mall" ? "bg-violet-500" : "bg-gray-400"}`} />
                      {poi.name}
                    </span>
                    {poi.distance_min != null && <span className="text-xs text-gray-500">{poi.distance_min} min walk</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Map */}
          {listing.lat && listing.lon && (
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h2 className="text-sm font-semibold text-gray-900 mb-3">Location</h2>
              <PropertyMap lat={listing.lat} lon={listing.lon} title={listing.title} pois={listing.nearby_pois} />
            </div>
          )}

          {/* Area blurb */}
          {listing.area_blurb && (
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h2 className="text-sm font-semibold text-gray-900 mb-2">About {listing.area_name}</h2>
              <p className="text-sm text-gray-600 leading-relaxed">{listing.area_blurb}</p>
            </div>
          )}
        </div>

        {/* Right: chat panel */}
        <div className="lg:col-span-2">
          {/* Mobile tab switcher */}
          <div className="lg:hidden flex border-b border-gray-200 mb-4">
            <button onClick={() => setActiveTab("details")} className={`flex-1 py-2 text-sm font-medium text-center border-b-2 transition-colors ${activeTab === "details" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500"}`}>
              Details
            </button>
            <button onClick={() => setActiveTab("chat")} className={`flex-1 py-2 text-sm font-medium text-center border-b-2 transition-colors ${activeTab === "chat" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500"}`}>
              Chat
            </button>
          </div>

          <div className={`lg:block ${activeTab === "chat" ? "block" : "hidden"}`}>
            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden sticky top-16" style={{ height: "calc(100vh - 120px)" }}>
              <PropertyChat
                propertyId={id}
                propertyTitle={listing.title}
                areaName={listing.area_name}
                autoFocus={chatMode}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Similar properties */}
      {similar.length > 0 && (
        <div className="mt-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Similar properties</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {similar.slice(0, 6).map((l) => <ListingCard key={l.id} listing={l} />)}
          </div>
        </div>
      )}
    </div>
  );
}
