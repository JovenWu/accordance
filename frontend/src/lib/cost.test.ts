import { describe, expect, it } from "vitest";

import { formatCost } from "./cost";

// Always 4 decimals. A single report can cost well under a cent (a measured
// 150-disclosure run came to $0.0710), so 2dp collapsed real spend to "$0.07"
// or "$0.00" and made per-run figures useless to compare.
describe("formatCost", () => {
  it("four decimals for normal amounts", () => expect(formatCost(4.125)).toBe("$4.1250"));
  it("four decimals for sub-cent amounts", () => expect(formatCost(0.0042)).toBe("$0.0042"));
  it("zero renders as $0.0000, not $0.00", () => expect(formatCost(0)).toBe("$0.0000"));
  it("rounds rather than truncating", () => expect(formatCost(0.00005)).toBe("$0.0001"));
});
