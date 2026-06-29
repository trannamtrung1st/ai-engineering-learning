import type { GeoPlatform } from "@wecheck/domain";

/** FR-10 — suspiciously perfect GPS accuracy below this threshold (meters). */
export const SPOOF_ACCURACY_THRESHOLD_METERS = 2;

export interface SpoofMetadataInput {
  mockLocationDetected?: boolean;
  accuracyMeters?: number;
  platform?: GeoPlatform | string;
}

export interface SpoofEvaluation {
  spoofSuspected: boolean;
  spoofFlags: Record<string, unknown> | null;
}

/**
 * FR-10 / AC-10 — baseline mock-location and perfect-accuracy heuristics.
 * Runs before radius check per validation-rules §5.1 step 12.
 */
export function evaluateSpoofHeuristics(
  metadata: SpoofMetadataInput | undefined,
): SpoofEvaluation {
  if (!metadata) {
    return { spoofSuspected: false, spoofFlags: null };
  }

  const flags: Record<string, unknown> = {};

  if (metadata.mockLocationDetected === true) {
    flags.mockLocationDetected = true;
  }

  if (metadata.platform !== undefined) {
    flags.platform = metadata.platform;
  }

  if (metadata.accuracyMeters !== undefined) {
    flags.accuracyMeters = metadata.accuracyMeters;
  }

  if (metadata.mockLocationDetected === true) {
    return { spoofSuspected: true, spoofFlags: flags };
  }

  if (
    typeof metadata.accuracyMeters === "number" &&
    metadata.accuracyMeters >= 0 &&
    metadata.accuracyMeters < SPOOF_ACCURACY_THRESHOLD_METERS
  ) {
    return { spoofSuspected: true, spoofFlags: flags };
  }

  return {
    spoofSuspected: false,
    spoofFlags: Object.keys(flags).length > 0 ? flags : null,
  };
}
