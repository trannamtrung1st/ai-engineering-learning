export { authRoutes } from "./routes.js";
export { authService } from "./service.js";
export { hashPassword, verifyPassword, TEST_PASSWORD_HASH } from "./password.js";
export {
  normalizeEmail,
  selectJwtRole,
  validateLoginInput,
  validateRegisterInput,
} from "./validation.js";
