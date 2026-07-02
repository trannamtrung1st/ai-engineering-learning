"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const drizzle_kit_1 = require("drizzle-kit");
require("dotenv/config");
exports.default = (0, drizzle_kit_1.defineConfig)({
    schema: './src/infra/db/schema.ts',
    out: '../supabase/migrations',
    dialect: 'postgresql',
    dbCredentials: { url: process.env.DATABASE_URL },
});
//# sourceMappingURL=drizzle.config.js.map