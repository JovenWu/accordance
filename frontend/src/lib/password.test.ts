import { describe, expect, it } from "vitest";

import { generatePassword } from "./password";

describe("generatePassword", () => {
  it("returns a string of the requested length", () => {
    expect(generatePassword(16)).toHaveLength(16);
    expect(generatePassword(24)).toHaveLength(24);
  });

  it("is at least 8 chars by default and varies", () => {
    const a = generatePassword();
    expect(a.length).toBeGreaterThanOrEqual(8);
    expect(generatePassword()).not.toBe(a);
  });
});
