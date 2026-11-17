import assert from "node:assert/strict";
import test from "node:test";

import { riskAssessmentLabel, riskProxyLabel } from "../src/lib/risk-display.js";

test("unknown and partial assessments never display a percentage", () => {
  assert.equal(riskAssessmentLabel(null, "unavailable"), "Risk data unavailable");
  assert.equal(riskAssessmentLabel(0, undefined), "Risk data unavailable");
  assert.equal(riskAssessmentLabel(0, "partial"), "Risk data unavailable");
  assert.match(riskProxyLabel(0, "unavailable"), /Risk data unavailable/);
});

test("verified zero and known nonzero assessments remain distinguishable", () => {
  assert.equal(
    riskAssessmentLabel(0, "verified"),
    "0% reported disruption risk (verified; not a safety guarantee)",
  );
  assert.equal(riskAssessmentLabel(0.25, "assumed"), "25% estimated disruption risk (assumed)");
  assert.equal(riskProxyLabel(0.25, "assumed"), "25% risk proxy");
});
