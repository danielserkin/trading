import test from "node:test";
import assert from "node:assert/strict";

import worker, {constantTimeEqual, deleteMonitor, issueToken, mutateMonitor, verifyToken} from "../src/index.js";

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
  assert.match(result.headers.get("Access-Control-Allow-Methods"), /DELETE/);
});

test("monitor survives a new session and can pause and resume without its old card", () => {
  const state = {
    session:{run_id:"run-1", date:"2026-09-02", generated_at:"2026-09-02T12:00:00Z", cards:[{
      id:"trade-1", monitorable:true, asset:"USDJPY", direction:"BUY", order_type:"BUY STOP",
      valid_until:"2026-09-03T00:00:00Z", proxy_symbol:"USDJPY=X", provider:"test", source:"technical_market_scan",
    }]},
    monitors:{}, events:[],
  };
  mutateMonitor(state, "trade-1", {action:"activate", entry:160.268, stop_loss:160.115, take_profit:160.513, volume:0.2, display_decimals:3}, "2026-09-02T12:05:00Z");
  const activation = state.monitors["trade-1"].activation_id;
  state.session = {run_id:"run-2", date:"2026-09-03", cards:[]};
  mutateMonitor(state, "trade-1", {action:"pause"}, "2026-09-03T10:00:00Z");
  assert.equal(state.monitors["trade-1"].status, "paused");
  mutateMonitor(state, "trade-1", {action:"resume"}, "2026-09-03T11:00:00Z");
  assert.equal(state.monitors["trade-1"].enabled, true);
  assert.equal(state.monitors["trade-1"].session_run_id, "run-1");
  assert.equal(state.monitors["trade-1"].session_date, "2026-09-02");
  assert.equal(state.monitors["trade-1"].display_decimals, 3);
  assert.notEqual(state.monitors["trade-1"].activation_id, activation);
  assert.equal(state.monitors["trade-1"].activated_at, "2026-09-02T12:05:00Z");
});

test("active monitor must be paused before deletion", () => {
  const state = {monitors:{trade:{trade_id:"trade", asset:"EURUSD", enabled:true, status:"active"}}, events:[]};
  assert.throws(() => deleteMonitor(state, "trade"), /Pausa/);
  mutateMonitor(state, "trade", {action:"pause"}, "2026-09-02T12:00:00Z");
  deleteMonitor(state, "trade");
  assert.equal(state.monitors.trade, undefined);
});

test("display decimals are restricted to one through five", () => {
  const state = {session:{cards:[{id:"trade", monitorable:true, asset:"EURUSD", direction:"BUY"}]}, monitors:{}, events:[]};
  assert.throws(
    () => mutateMonitor(state, "trade", {action:"activate", entry:1.1, stop_loss:1.09, take_profit:1.12, display_decimals:6}),
    /decimales/,
  );
});
