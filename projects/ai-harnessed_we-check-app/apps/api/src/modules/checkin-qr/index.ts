export { CheckInService, truncateCheckInTables } from "./check-in-service.js";
export { QrScheduler } from "./qr-scheduler.js";
export { registerCheckInQrRoutes } from "./routes.js";
export { evaluateSpoofHeuristics, SPOOF_ACCURACY_THRESHOLD_METERS } from "./spoof-heuristics.js";
export { verifyLocation } from "./geo-verification.js";
export {
  computeTokenExpiresAt,
  isQrTokenExpired,
  qrTokenRemainingMs,
} from "@wecheck/domain";
