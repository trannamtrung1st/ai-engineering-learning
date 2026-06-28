export { NotificationService, PolicyRepository } from "./notification-service.js";
export { registerNotificationRoutes } from "./routes.js";
export {
  NotificationRepository,
  PolicyRepository as AbsencePolicyRepository,
  truncateNotificationTables,
  POLICY_KEY_ABSENCE_THRESHOLD,
} from "./repositories.js";
export {
  computeAbsenceRate,
  exceedsAbsenceThreshold,
  DEFAULT_ABSENCE_THRESHOLD_PERCENT,
} from "./absence-threshold.js";
export {
  validateAbsenceThresholdBody,
  validateNotificationListQuery,
} from "./validation.js";
export type {
  AbsenceThresholdPayload,
  NotificationDto,
  NotificationListQuery,
} from "./types.js";
