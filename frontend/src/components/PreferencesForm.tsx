"use client";

import { useState, useEffect } from "react";
import type { Preferences } from "@/lib/api";
import { getPreferences, updatePreferences } from "@/lib/api";

const ALL_AREAS = [
  "JLT", "Dubai Marina", "Downtown Dubai", "Business Bay", "DIFC",
  "Palm Jumeirah", "Jumeirah", "Al Barsha", "Deira", "Bur Dubai",
  "Mirdif", "Dubai Silicon Oasis",
];

interface PreferencesFormProps {
  onSaved?: () => void;
  compact?: boolean;
}

export default function PreferencesForm({ onSaved, compact }: PreferencesFormProps) {
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getPreferences()
      .then((p) => { setPrefs(p); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, []);

  if (!loaded) return <div className="animate-pulse h-32 bg-gray-100 rounded-lg" />;
  if (!prefs) return <p className="text-sm text-gray-500">No preferences configured.</p>;

  const update = (partial: Partial<Preferences>) => setPrefs({ ...prefs, ...partial });

  const toggleArea = (area: string) => {
    const areas = prefs.areas.includes(area)
      ? prefs.areas.filter((a) => a !== area)
      : [...prefs.areas, area];
    update({ areas });
  };

  const save = async () => {
    setSaving(true);
    try { await updatePreferences(prefs); onSaved?.(); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Min budget (AED/yr)</label>
          <input type="number" value={prefs.min_price ?? ""} onChange={(e) => update({ min_price: e.target.value ? Number(e.target.value) : null })} className="w-full border rounded-md px-3 py-2 text-sm" placeholder="40,000" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Max budget (AED/yr)</label>
          <input type="number" value={prefs.max_price ?? ""} onChange={(e) => update({ max_price: e.target.value ? Number(e.target.value) : null })} className="w-full border rounded-md px-3 py-2 text-sm" placeholder="120,000" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Bedrooms</label>
          <div className="flex gap-1.5">
            {[0, 1, 2, 3].map((b) => (
              <button key={b} onClick={() => update({ bedrooms: prefs.bedrooms.includes(b) ? prefs.bedrooms.filter((x) => x !== b) : [...prefs.bedrooms, b] })} className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${prefs.bedrooms.includes(b) ? "bg-blue-600 text-white border-blue-600" : "bg-white text-gray-700 border-gray-300 hover:border-blue-400"}`}>
                {b === 0 ? "Studio" : `${b}BR`}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Min bathrooms</label>
          <input type="number" min={0} value={prefs.min_bathrooms ?? ""} onChange={(e) => update({ min_bathrooms: e.target.value ? Number(e.target.value) : null })} className="w-full border rounded-md px-3 py-2 text-sm" />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Furnished</label>
        <div className="flex gap-1.5">
          {[{ v: null as number | null, label: "Any" }, { v: 1, label: "Furnished" }, { v: 0, label: "Unfurnished" }].map((opt) => (
            <button key={String(opt.v)} onClick={() => update({ furnished: opt.v })} className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${prefs.furnished === opt.v ? "bg-blue-600 text-white border-blue-600" : "bg-white text-gray-700 border-gray-300 hover:border-blue-400"}`}>
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {!compact && (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Areas</label>
          <div className="flex flex-wrap gap-1.5">
            {ALL_AREAS.map((area) => (
              <button key={area} onClick={() => toggleArea(area)} className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${prefs.areas.includes(area) ? "bg-blue-600 text-white border-blue-600" : "bg-white text-gray-700 border-gray-300 hover:border-blue-400"}`}>
                {area}
              </button>
            ))}
          </div>
        </div>
      )}

      <button onClick={save} disabled={saving} className="w-full bg-blue-600 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors">
        {saving ? "Saving..." : "Save preferences"}
      </button>
    </div>
  );
}
