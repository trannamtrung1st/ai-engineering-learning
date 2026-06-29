import { MapPin } from "lucide-react";
import { useCallback, useRef } from "react";
import { Button } from "@/components/ui/button";
import { PREVIEW_ROOM_GPS } from "@/lib/preview-fixtures";

const DEFAULT_CENTER = {
  lat: PREVIEW_ROOM_GPS.latitude,
  lng: PREVIEW_ROOM_GPS.longitude,
};

const ZOOM = 16;
const TILE_SIZE = 256;

function lonToTileX(lon: number, zoom: number): number {
  return ((lon + 180) / 360) * 2 ** zoom;
}

function latToTileY(lat: number, zoom: number): number {
  const rad = (lat * Math.PI) / 180;
  return (
    ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * 2 ** zoom
  );
}

function tileToLon(x: number, zoom: number): number {
  return (x / 2 ** zoom) * 360 - 180;
}

function tileToLat(y: number, zoom: number): number {
  const n = Math.PI - (2 * Math.PI * y) / 2 ** zoom;
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

function osmTileUrl(x: number, y: number, z: number): string {
  return `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
}

export interface GpsMapPickerProps {
  latitude: number | null;
  longitude: number | null;
  radiusMeters: number;
  onChange: (lat: number, lng: number) => void;
  readOnly?: boolean;
}

/** FR-04 / BR-07 — interactive OSM map for room GPS selection */
export function GpsMapPicker({
  latitude,
  longitude,
  radiusMeters,
  onChange,
  readOnly = false,
}: GpsMapPickerProps) {
  const mapRef = useRef<HTMLDivElement>(null);

  const centerLat = latitude ?? DEFAULT_CENTER.lat;
  const centerLng = longitude ?? DEFAULT_CENTER.lng;

  const centerTileX = lonToTileX(centerLng, ZOOM);
  const centerTileY = latToTileY(centerLat, ZOOM);
  const baseX = Math.floor(centerTileX);
  const baseY = Math.floor(centerTileY);

  const handleMapClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (readOnly || !mapRef.current) return;
      const rect = mapRef.current.getBoundingClientRect();
      const relX = event.clientX - rect.left;
      const relY = event.clientY - rect.top;
      const width = rect.width;
      const height = rect.height;

      const offsetX = centerTileX - baseX - 0.5;
      const offsetY = centerTileY - baseY - 0.5;
      const clickTileX = baseX + (relX / width - 0.5) + offsetX + 0.5;
      const clickTileY = baseY + (relY / height - 0.5) + offsetY + 0.5;

      const lng = tileToLon(clickTileX, ZOOM);
      const lat = tileToLat(clickTileY, ZOOM);
      onChange(
        Math.round(lat * 1_000_000) / 1_000_000,
        Math.round(lng * 1_000_000) / 1_000_000,
      );
    },
    [readOnly, onChange, centerTileX, centerTileY, baseX, baseY],
  );

  const handleUseCurrentLocation = () => {
    if (readOnly || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        onChange(pos.coords.latitude, pos.coords.longitude);
      },
      () => {
        /* permission denied — user can click map instead */
      },
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  };

  const hasPin = latitude !== null && longitude !== null;
  const metersPerPixel =
    (156_543.03392 * Math.cos((centerLat * Math.PI) / 180)) / 2 ** ZOOM;
  const radiusPx = Math.min(radiusMeters / metersPerPixel, 120);

  return (
    <div className="flex flex-col gap-3" data-testid="gps-map-picker">
      <div
        ref={mapRef}
        role="application"
        aria-label="Bản đồ chọn tọa độ phòng học"
        className={`relative aspect-[4/3] w-full overflow-hidden rounded-md border border-border bg-surface-muted ${
          readOnly ? "cursor-default" : "cursor-crosshair"
        }`}
        onClick={handleMapClick}
        onKeyDown={(e) => {
          if (readOnly) return;
          const step = 0.0001;
          if (!hasPin) return;
          if (e.key === "ArrowUp") onChange(latitude! + step, longitude!);
          if (e.key === "ArrowDown") onChange(latitude! - step, longitude!);
          if (e.key === "ArrowLeft") onChange(latitude!, longitude! - step);
          if (e.key === "ArrowRight") onChange(latitude!, longitude! + step);
        }}
        tabIndex={readOnly ? -1 : 0}
      >
        <div
          className="absolute inset-0 grid grid-cols-3 grid-rows-3"
          style={{ width: "300%", height: "300%", left: "-100%", top: "-100%" }}
        >
          {[-1, 0, 1].flatMap((dy) =>
            [-1, 0, 1].map((dx) => {
              const x = baseX + dx;
              const y = baseY + dy;
              return (
                <img
                  key={`${x}-${y}`}
                  src={osmTileUrl(x, y, ZOOM)}
                  alt=""
                  className="h-full w-full object-cover"
                  draggable={false}
                  style={{ width: TILE_SIZE, height: TILE_SIZE }}
                />
              );
            }),
          )}
        </div>

        {hasPin ? (
          <>
            <div
              className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-primary-500/60 bg-primary-500/10"
              style={{
                width: radiusPx * 2,
                height: radiusPx * 2,
              }}
              aria-hidden="true"
            />
            <div
              className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-primary-700"
              data-testid="gps-map-pin"
            >
              <MapPin className="h-8 w-8 drop-shadow" aria-hidden="true" />
            </div>
          </>
        ) : (
          <p className="absolute inset-0 flex items-center justify-center bg-surface/60 px-4 text-center text-small text-text-secondary">
            Nhấn vào bản đồ để đặt vị trí phòng học
          </p>
        )}
      </div>

      {!readOnly ? (
        <Button
          type="button"
          variant="ghost"
          className="self-start"
          onClick={handleUseCurrentLocation}
          data-testid="gps-use-current-location"
        >
          Dùng vị trí hiện tại
        </Button>
      ) : null}
    </div>
  );
}
