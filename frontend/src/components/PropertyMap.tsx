"use client";

import { useEffect, useRef } from "react";
import type { POISummary } from "@/lib/api";

interface PropertyMapProps {
  lat: number;
  lon: number;
  title: string;
  pois: POISummary[];
}

const POI_COLORS: Record<string, string> = {
  metro: "#e11d48",
  mall: "#7c3aed",
};

export default function PropertyMap({ lat, lon, title, pois }: PropertyMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapInstance = useRef<any>(null);

  useEffect(() => {
    if (!mapRef.current) return;
    let cancelled = false;

    import("leaflet").then((L) => {
      // Cleanup ran before async import resolved — bail out
      if (cancelled || !mapRef.current) return;
      // Already initialized (e.g. StrictMode double-invoke)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((mapRef.current as any)._leaflet_id) return;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      const map = L.map(mapRef.current, { scrollWheelZoom: false }).setView([lat, lon], 14);

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
        maxZoom: 18,
      }).addTo(map);

      L.marker([lat, lon]).addTo(map).bindPopup(`<b>${title}</b>`).openPopup();

      pois.forEach((poi) => {
        const color = POI_COLORS[poi.type] || "#6b7280";
        const label = poi.type === "metro" ? "M" : poi.type === "mall" ? "S" : poi.type[0].toUpperCase();
        const icon = L.divIcon({
          className: "",
          html: `<div style="background:${color};color:white;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.3)">${label}</div>`,
          iconSize: [24, 24],
          iconAnchor: [12, 12],
        });
        L.marker([poi.lat, poi.lon], { icon }).addTo(map).bindPopup(`<b>${poi.name}</b><br>${poi.type}${poi.distance_min ? ` (${poi.distance_min} min walk)` : ""}`);
      });

      mapInstance.current = map;
    });

    return () => {
      cancelled = true;
      if (mapInstance.current) { mapInstance.current.remove(); mapInstance.current = null; }
    };
  }, [lat, lon, title, pois]);

  return (
    <div className="relative">
      <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossOrigin="" />
      <div ref={mapRef} className="w-full h-80 rounded-lg border border-gray-200" />
      <div className="absolute bottom-3 left-3 bg-white/90 backdrop-blur rounded-md px-2.5 py-1.5 text-[10px] flex gap-3 shadow-sm z-[1000]">
        {Object.entries(POI_COLORS).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: color }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}
