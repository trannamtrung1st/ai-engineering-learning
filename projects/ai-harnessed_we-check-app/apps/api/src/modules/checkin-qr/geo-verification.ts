import { haversineDistanceMeters, isWithinRadius } from "@wecheck/domain";
import {
  evaluateSpoofHeuristics,
  type SpoofMetadataInput,
} from "./spoof-heuristics.js";

export interface GeoVerificationResult {
  distanceMeters: number;
  withinRadius: boolean;
  spoofSuspected: boolean;
  spoofFlags: Record<string, unknown> | null;
}

export function verifyLocation(
  roomLat: number,
  roomLng: number,
  clientLat: number,
  clientLng: number,
  radiusMeters: number,
  spoofMetadata: SpoofMetadataInput | undefined,
): GeoVerificationResult {
  const distanceMeters = haversineDistanceMeters(
    roomLat,
    roomLng,
    clientLat,
    clientLng,
  );
  const spoof = evaluateSpoofHeuristics(spoofMetadata);

  return {
    distanceMeters,
    withinRadius: isWithinRadius(
      roomLat,
      roomLng,
      clientLat,
      clientLng,
      radiusMeters,
    ),
    spoofSuspected: spoof.spoofSuspected,
    spoofFlags: spoof.spoofFlags,
  };
}
