import test from "node:test";
import assert from "node:assert/strict";

import worker, {constantTimeEqual, issueToken, verifyToken} from "../src/index.js";

test("constant-time comparison handles matching and empty values", () => {
  assert.equal(constantTimeEqual("same", "same"), true);
  assert.equal(constantTimeEqual("same", "different"), false);
  assert.equal(constantTimeEqual("", ""), true);
  assert.equal(constantTimeEqual("", "x"), false);
});

test("issued session token verifies and tampering fails", async () => {
  const env = {APP_SESSION_SECRET: "a-long-test-secret-that-is-not-production"};
  const token = await issueToken(env);
  const valid = new Request("https://worker.test/state", {headers:{Authorization:`Bearer ${token}`}});
  assert.equal(await verifyToken(valid, env), true);

  const tampered = new Request("https://worker.test/state", {headers:{Authorization:`Bearer ${token}x`}});
  assert.equal(await verifyToken(tampered, env), false);
});

test("missing signing secret is never authorized", async () => {
  const request = new Request("https://worker.test/state", {headers:{Authorization:"Bearer anything.anything"}});
  assert.equal(await verifyToken(request, {}), false);
});

test("CORS preflight returns an empty successful response", async () => {
  const request = new Request("https://worker.test/auth", {
    method:"OPTIONS",
    headers:{Origin:"https://danielserkin.github.io"},
  });
  const result = await worker.fetch(request, {ALLOWED_ORIGIN:"*"});
  assert.equal(result.status, 204);
  assert.equal(await result.text(), "");
  assert.equal(result.headers.get("Access-Control-Allow-Origin"), "*");
});
