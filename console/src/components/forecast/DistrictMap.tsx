import { useEffect, useRef, useState } from "react";
import type maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, Marker } from "maplibre-gl";
import { EVENT_FAMILY_LABELS, formatProbability, probabilityColor } from "@/lib/format";
import { PROBABILITY_RAMP } from "@/lib/format";
import type { District, ForecastSummary } from "@/lib/api/types";

/**
 * The district map.
 *
 * A basemap is an external network dependency, and this console is expected to
 * run in environments that have no route to a tile server. So the style URL is
 * configuration (`VITE_MAP_STYLE_URL`), and when it is absent or fails to load
 * the map is replaced by `MapUnavailable` — which points at the ranked table
 * rather than pretending the map is merely still loading.
 *
 * MapLibre itself is imported dynamically, inside the effect, for the same
 * reason: it is 800 kB serving one panel on one route. With no style URL
 * configured it is never fetched at all, and the ten routes that draw no map
 * never pay for it.
 *
 * The map is never the only way to read the data. Everything encoded here is
 * also in the table below it, because a choropleth is unusable with a screen
 * reader and unreliable for a colour-blind reader even with a CVD-safe ramp.
 */

const STYLE_URL = (import.meta.env.VITE_MAP_STYLE_URL ?? "").trim();

export function MapUnavailable({ reason }: { reason: string }) {
  return (
    <div className="flex h-full min-h-[320px] flex-col items-center justify-center rounded-lg border border-uncertainty-400/40 bg-uncertainty-400/5 p-6 text-center">
      <p aria-hidden className="text-2xl">🗺</p>
      <p className="mt-2 text-sm font-semibold">Map unavailable</p>
      <p className="mt-1 max-w-sm text-sm muted">{reason}</p>
      <p className="mt-3 max-w-sm text-2xs muted">
        Nothing is lost: the ranked table below carries the same districts, probabilities,
        intervals and statuses, and is the authoritative view of this data.
      </p>
    </div>
  );
}

export function DistrictMap({
  districts,
  forecasts,
  onSelect,
}: {
  districts: District[];
  forecasts: ForecastSummary[];
  onSelect: (forecast: ForecastSummary) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  // The loaded module, held in state so the marker effect re-runs once it lands.
  const [gl, setGl] = useState<typeof maplibregl | null>(null);

  // The strongest forecast per district: a district with three families showing
  // is one dot, coloured by its highest probability, and the table disambiguates.
  const byDistrict = new Map<string, ForecastSummary>();
  for (const forecast of forecasts) {
    const existing = byDistrict.get(forecast.district_id);
    if (!existing || forecast.calibrated_probability > existing.calibrated_probability) {
      byDistrict.set(forecast.district_id, forecast);
    }
  }

  useEffect(() => {
    if (!STYLE_URL || !container.current) return;
    let cancelled = false;

    void (async () => {
      try {
        const [{ default: maplibregl }] = await Promise.all([
          import("maplibre-gl"),
          import("maplibre-gl/dist/maplibre-gl.css"),
        ]);
        if (cancelled || !container.current || map.current) return;

        const instance = new maplibregl.Map({
          container: container.current,
          style: STYLE_URL,
          center: [79, 22],
          zoom: 3.6,
          attributionControl: { compact: true },
        });
        instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        instance.on("error", (event) => {
          setFailed(
            `The basemap style at ${STYLE_URL} could not be loaded (${
              event.error?.message ?? "unknown error"
            }).`,
          );
        });
        map.current = instance;
        setGl(() => maplibregl);
      } catch (error) {
        setFailed(
          error instanceof Error
            ? `MapLibre could not be loaded: ${error.message}`
            : "MapLibre could not be loaded.",
        );
      }
    })();

    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !gl) return;
    const markers: Marker[] = [];
    for (const district of districts) {
      const forecast = byDistrict.get(district.district_id);
      if (!forecast) continue;
      const element = document.createElement("button");
      element.type = "button";
      element.setAttribute(
        "aria-label",
        `${district.name}, ${district.state}: ${formatProbability(forecast.calibrated_probability)}`,
      );
      element.style.cssText = `width:14px;height:14px;border-radius:9999px;border:1px solid #0b1220;cursor:pointer;background:${probabilityColor(
        forecast.calibrated_probability,
      )}`;
      element.addEventListener("click", () => onSelect(forecast));
      markers.push(
        new gl.Marker({ element })
          .setLngLat([district.centroid.lon, district.centroid.lat])
          .addTo(instance),
      );
    }
    return () => markers.forEach((marker) => marker.remove());
  }, [districts, forecasts, gl]);

  if (!STYLE_URL) {
    return (
      <MapUnavailable reason="No basemap is configured. Set VITE_MAP_STYLE_URL to a MapLibre style to enable the map; the console deliberately ships without a default tile provider so it never makes an unannounced third-party request." />
    );
  }
  if (failed) return <MapUnavailable reason={failed} />;

  return (
    <div className="relative h-full min-h-[320px]">
      <div ref={container} className="h-full min-h-[320px] rounded-lg" />
      <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-[rgb(var(--surface))]/90 px-2 py-1.5 text-2xs">
        <p className="mb-1 font-semibold">Calibrated probability</p>
        <div className="flex items-center gap-1">
          <span className="tabular">0%</span>
          <span className="flex h-2 w-24">
            {PROBABILITY_RAMP.map((colour) => (
              <span key={colour} className="h-full flex-1" style={{ background: colour }} />
            ))}
          </span>
          <span className="tabular">100%</span>
        </div>
      </div>
    </div>
  );
}

export function MapLegendNote({ family }: { family: string | null }) {
  return (
    <p className="text-2xs muted">
      One marker per district, coloured by the highest calibrated probability across
      {family ? ` ${EVENT_FAMILY_LABELS[family as keyof typeof EVENT_FAMILY_LABELS] ?? family}` : " all event families"}.
      Colour is a summary; the table is the record.
    </p>
  );
}
