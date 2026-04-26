import Link from "next/link";
import type { ListingSummary, RankedListing } from "@/lib/api";
import ScoreBadge from "./ScoreBadge";

interface ListingCardProps {
  listing: ListingSummary | RankedListing;
  ranked?: boolean;
}

function isRanked(l: ListingSummary | RankedListing): l is RankedListing {
  return "score" in l;
}


export default function ListingCard({ listing }: ListingCardProps) {
  const l = listing;

  // Priority: real listing photo > static OSM map > gradient placeholder
  const heroImg = l.image_url
    ?? (l.lat && l.lon
      ? `https://staticmap.openstreetmap.de/staticmap.php?center=${l.lat},${l.lon}&zoom=15&size=400x160&markers=${l.lat},${l.lon},ol-marker`
      : null);

  return (
    <Link
      href={`/property/${l.id}`}
      className="block bg-white border border-gray-200 rounded-lg overflow-hidden hover:shadow-md transition-shadow"
    >
      {/* Image / map thumbnail */}
      <div className="h-36 relative overflow-hidden bg-gradient-to-br from-slate-100 to-blue-50">
        {heroImg ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={heroImg}
            alt={l.area_name || "Property location"}
            className="w-full h-full object-cover"
            loading="lazy"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-blue-200 text-sm font-medium">
            {l.area_name || "Dubai"}
          </div>
        )}
        {/* Platform badge overlay */}
        {l.platform_name && (
          <span className="absolute top-2 right-2 text-[10px] text-white bg-black/40 backdrop-blur-sm px-2 py-0.5 rounded">
            {l.platform_name.replace("_", " ")}
          </span>
        )}
      </div>

      <div className="p-4 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold text-gray-900 line-clamp-2 leading-snug">
            {l.title}
          </h3>
          {isRanked(l) && <ScoreBadge score={l.score} size="sm" />}
        </div>

        <p className="text-lg font-bold text-blue-700">
          {l.price_aed ? `AED ${l.price_aed.toLocaleString()}` : "Price N/A"}
          <span className="text-xs font-normal text-gray-500"> /year</span>
        </p>

        <p className="text-xs text-gray-500">
          {l.beds != null && `${l.beds} bed`}
          {l.baths != null && ` · ${l.baths} bath`}
          {l.size_sqft != null && ` · ${l.size_sqft.toLocaleString()} sqft`}
        </p>

        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">{l.area_name}</span>
        </div>

        {isRanked(l) && (
          <div className="pt-1 border-t border-gray-100 text-[11px] text-gray-500 space-y-0.5">
            <p>Metro: {l.metro_name} ({l.metro_min} min walk)</p>
            <p>Mall: {l.mall_name} ({l.mall_min} min walk)</p>
            <p className="flex gap-3 pt-0.5">
              <span>&#10003; Overall: {Math.round(l.score)}</span>
              <span>&#9733; Location: {l.score_location}</span>
              <span>&#9670; Value: {l.score_value}</span>
            </p>
          </div>
        )}
      </div>
    </Link>
  );
}
