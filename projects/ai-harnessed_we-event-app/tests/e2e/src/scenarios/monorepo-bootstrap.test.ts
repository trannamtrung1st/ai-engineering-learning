import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

const REPO_ROOT = join(import.meta.dirname, "../../../../");

function readPackageJson(relativePath: string): {
  name?: string;
  workspaces?: string[];
  scripts?: Record<string, string>;
} {
  const absolutePath = join(REPO_ROOT, relativePath);
  assert.ok(existsSync(absolutePath), `expected ${relativePath}`);
  return JSON.parse(readFileSync(absolutePath, "utf8")) as {
    name?: string;
    workspaces?: string[];
    scripts?: Record<string, string>;
  };
}

/**
 * NFR-14 maintainability baseline: npm workspaces monorepo enables operable
 * event configuration without ad-hoc tooling.
 */
describe("monorepo bootstrap (NFR-14)", () => {
  it("NFR-14: root package.json declares apps, packages, and tests workspaces", () => {
    const root = readPackageJson("package.json");
    assert.deepEqual([...(root.workspaces ?? [])].sort(), [
      "apps/*",
      "packages/*",
      "tests/*",
    ]);
    assert.ok(root.scripts?.["test:unit"]);
    assert.ok(root.scripts?.["test:integration"]);
    assert.ok(root.scripts?.["test:e2e"]);
  });

  it("NFR-14: completion workspace packages exist with @we-event scope", () => {
    const workspacePackages = [
      { path: "apps/api/package.json", name: "@we-event/api" },
      { path: "apps/web/package.json", name: "@we-event/web" },
      { path: "packages/domain/package.json", name: "@we-event/domain" },
      { path: "packages/config/package.json", name: "@we-event/config" },
    ];

    for (const entry of workspacePackages) {
      const pkg = readPackageJson(entry.path);
      assert.equal(pkg.name, entry.name, entry.path);
    }
  });

  it("NFR-14: api and web workspaces depend on shared domain package", () => {
    for (const path of ["apps/api/package.json", "apps/web/package.json"]) {
      const pkg = readPackageJson(path) as {
        dependencies?: Record<string, string>;
      };
      assert.equal(pkg.dependencies?.["@we-event/domain"], "*", path);
    }
  });
});
