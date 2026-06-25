/** API service entry — routes and middleware are added in the api-foundation slice. */
export const API_VERSION = "v1";
export const API_BASE_PATH = `/api/${API_VERSION}`;

export function getApiMetadata() {
  return {
    version: API_VERSION,
    basePath: API_BASE_PATH,
  };
}
