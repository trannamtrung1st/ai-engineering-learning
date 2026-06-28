import { PASSWORD_POLICY } from "@wecheck/domain";

export const API_VERSION = "v1";
export const API_BASE_PATH = "/api/v1";

export function getApiMetadata() {
  return {
    version: API_VERSION,
    basePath: API_BASE_PATH,
    passwordMinLength: PASSWORD_POLICY.MIN_LENGTH,
  };
}
