import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { getApiMetadata } from "./index.js";

describe("@wecheck/api monorepo bootstrap", () => {
  it("wires @wecheck/domain for NFR-14 password policy metadata", () => {
    const metadata = getApiMetadata();
    assert.equal(metadata.basePath, "/api/v1");
    assert.equal(metadata.version, "v1");
    assert.equal(metadata.passwordMinLength, 8);
  });
});
