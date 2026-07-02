import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");

function readComposeFile(name: string): string {
  return readFileSync(resolve(REPO_ROOT, name), "utf8");
}

describe("docker compose runtime config — FR-07 FR-16 NFR-16", () => {
  it("declares dev db and redis health checks with startup dependencies", () => {
    const compose = readComposeFile("docker-compose.yml");
    expect(compose).toMatch(/pg_isready/);
    expect(compose).toMatch(/redis-cli/);
    expect(compose).toMatch(/condition: service_healthy/);
    expect(compose).toMatch(/profiles: \[full-preview\]/);
  });

  it("declares isolated test stack services on offset ports", () => {
    const compose = readComposeFile("docker-compose.test.yml");
    expect(compose).toMatch(/5433:5432/);
    expect(compose).toMatch(/6380:6379/);
    expect(compose).toMatch(/9002:9000/);
    expect(compose).toMatch(/hesd_test/);
  });
});

describe("migration and seed hooks — AC-01 AC-11", () => {
  it("exposes db:migrate and db:seed scripts for compose one-off jobs", () => {
    const pkg = JSON.parse(readFileSync(resolve(REPO_ROOT, "package.json"), "utf8")) as {
      scripts: Record<string, string>;
    };
    expect(pkg.scripts["db:migrate"]).toContain("db-migrate.mjs");
    expect(pkg.scripts["db:seed"]).toContain("db-seed.mjs");
  });
});
