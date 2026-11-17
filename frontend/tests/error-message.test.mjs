import assert from "node:assert/strict";
import test from "node:test";
import { readableErrorMessage } from "../src/lib/error-message.js";

test("FastAPI validation detail arrays become readable field messages", () => {
  const message = readableErrorMessage(
    {
      detail: [
        {
          type: "greater_than_equal",
          loc: ["body", "disruptions", 0, "severity"],
          msg: "Input should be less than or equal to 1",
        },
        {
          type: "missing",
          loc: ["body", "attractions", 0, "visit_minutes"],
          msg: "Field required",
        },
      ],
    },
    "Fallback",
  );

  assert.equal(
    message,
    "disruptions[0].severity: Input should be less than or equal to 1; attractions[0].visit_minutes: Field required",
  );
  assert.doesNotMatch(message, /\[object Object\]/);
});

test("nested messages and string errors are extracted without object coercion", () => {
  assert.equal(
    readableErrorMessage({ error: { response: { message: "Scenario unavailable" } } }, "Fallback"),
    "Scenario unavailable",
  );
  assert.equal(readableErrorMessage({ detail: "Trip not found" }, "Fallback"), "Trip not found");
});

test("unreadable payloads use a useful fallback and cyclic objects are safe", () => {
  const cyclic = {};
  cyclic.detail = cyclic;
  assert.equal(
    readableErrorMessage(cyclic, "The operation could not be completed."),
    "The operation could not be completed.",
  );
  assert.equal(
    readableErrorMessage({}, "The operation could not be completed."),
    "The operation could not be completed.",
  );
});
