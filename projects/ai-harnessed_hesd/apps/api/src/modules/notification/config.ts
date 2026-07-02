/** M10 optional capability — disabled by default for MVP Should-scope (FR-26). */
export function isNotificationModuleEnabled(): boolean {
  const flag = process.env.NOTIFICATION_MODULE_ENABLED;
  if (flag === undefined || flag === "") {
    return false;
  }
  return flag === "true" || flag === "1";
}
