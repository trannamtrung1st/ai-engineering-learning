import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { migrateSchema } from "./migrate";
import * as schema from "./schema";

export function createDatabase(path = process.env.ATTENDLY_DB_PATH ?? "data/attendly.sqlite") {
  const resolvedPath = path === ":memory:" ? path : resolve(path);
  if (resolvedPath !== ":memory:") {
    mkdirSync(dirname(resolvedPath), { recursive: true });
  }

  const sqlite = new Database(resolvedPath);
  sqlite.pragma("foreign_keys = ON");
  migrateSchema(sqlite);
  const db = drizzle(sqlite, { schema });

  return { db, sqlite };
}

export type AttendlyDatabase = ReturnType<typeof createDatabase>["db"];

let applicationDatabase: ReturnType<typeof createDatabase> | undefined;

export function getDatabase() {
  applicationDatabase ??= createDatabase();
  return applicationDatabase;
}
