const STATE_PATH = "runtime/state.json";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function base64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function fromBase64(value) {
  const unpadded = value.replace(/\s/g, "");
  const clean = unpadded + "=".repeat((4 - (unpadded.length % 4)) % 4);
  const binary = atob(clean);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function toBase64(value) {
  let binary = "";
  for (const byte of encoder.encode(value)) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function constantTimeEqual(a, b) {
  const left = encoder.encode(String(a));
  const right = encoder.encode(String(b));
  let result = left.length ^ right.length;
  const length = Math.max(left.length, right.length, 1);
  for (let index = 0; index < length; index++) {
    const leftByte = left.length ? left[index % left.length] : 0;
    const rightByte = right.length ? right[index % right.length] : 0;
    result |= leftByte ^ rightByte;
  }
  return result === 0;
}

async function signature(value, secret) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), {name:"HMAC", hash:"SHA-256"}, false, ["sign"]);
  return base64Url(new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(value))));
}

async function issueToken(env) {
  const body = base64Url(encoder.encode(JSON.stringify({exp: Math.floor(Date.now() / 1000) + 12 * 3600, nonce: crypto.randomUUID()})));
  return `${body}.${await signature(body, env.APP_SESSION_SECRET)}`;
}

async function verifyToken(request, env) {
  if (!env.APP_SESSION_SECRET) return false;
  const header = request.headers.get("Authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  const [body, provided] = token.split(".");
  if (!body || !provided || !constantTimeEqual(provided, await signature(body, env.APP_SESSION_SECRET))) return false;
  try {
    const payload = JSON.parse(decoder.decode(fromBase64(body.replaceAll("-", "+").replaceAll("_", "/"))));
    return Number(payload.exp) > Date.now() / 1000;
  } catch { return false; }
}

function allowedOrigin(request, env) {
  const configured = env.ALLOWED_ORIGIN || "*";
  const origin = request.headers.get("Origin") || "";
  return configured === "*" || configured.split(",").map((item) => item.trim()).includes(origin) ? (configured === "*" ? "*" : origin) : "null";
}

function response(request, env, payload, status = 200) {
  const responseBody = status === 204 ? null : JSON.stringify(payload);
  return new Response(responseBody, {status, headers:{
    "Content-Type":"application/json; charset=utf-8",
    "Access-Control-Allow-Origin":allowedOrigin(request, env),
    "Access-Control-Allow-Headers":"Authorization, Content-Type",
    "Access-Control-Allow-Methods":"GET, POST, PUT, DELETE, OPTIONS",
    "Cache-Control":"no-store",
  }});
}

function githubHeaders(env) {
  return {
    "Accept":"application/vnd.github+json",
    "Authorization":`Bearer ${env.GH_TOKEN}`,
    "X-GitHub-Api-Version":"2022-11-28",
    "User-Agent":"trading-control-worker/1.0",
    "Content-Type":"application/json",
  };
}

function githubBase(env) {
  if (!env.GH_OWNER || !env.GH_REPO || !env.GH_TOKEN) throw new Error("Worker GitHub configuration is incomplete");
  return `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}`;
}

async function readState(env) {
  const branch = env.DATA_BRANCH || "runtime-data";
  const result = await fetch(`${githubBase(env)}/contents/${STATE_PATH}?ref=${encodeURIComponent(branch)}`, {headers:githubHeaders(env)});
  if (result.status === 404) throw new Error("La rama runtime-data todavía no fue inicializada");
  if (!result.ok) throw new Error(`GitHub state read failed (${result.status})`);
  const item = await result.json();
  return {state:JSON.parse(decoder.decode(fromBase64(item.content))), sha:item.sha};
}

async function updateState(env, message, mutate) {
  for (let attempt = 0; attempt < 4; attempt++) {
    const {state, sha} = await readState(env);
    await mutate(state);
    state.updated_at = new Date().toISOString();
    const result = await fetch(`${githubBase(env)}/contents/${STATE_PATH}`, {
      method:"PUT", headers:githubHeaders(env), body:JSON.stringify({
        message, branch:env.DATA_BRANCH || "runtime-data", sha,
        content:toBase64(`${JSON.stringify(state, null, 2)}\n`),
      }),
    });
    if (result.ok) return state;
    if (![409, 422].includes(result.status) || attempt === 3) throw new Error(`GitHub state write failed (${result.status})`);
    await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }
  throw new Error("No se pudo actualizar el estado");
}

async function dispatch(env, eventType, payload = {}) {
  const result = await fetch(`${githubBase(env)}/dispatches`, {
    method:"POST", headers:githubHeaders(env), body:JSON.stringify({event_type:eventType, client_payload:payload}),
  });
  if (!result.ok) throw new Error(`GitHub workflow dispatch failed (${result.status})`);
}

function event(state, level, message) {
  state.events ||= [];
  state.events.push({at:new Date().toISOString(), level, message});
  state.events = state.events.slice(-150);
}

function monitorAction(input) {
  if (input.action) return String(input.action).toLowerCase();
  return Boolean(input.enabled) ? "activate" : "pause";
}

function validDisplayDecimals(value) {
  const decimals = Number(value ?? 3);
  if (!Number.isInteger(decimals) || decimals < 1 || decimals > 5) throw new Error("Los decimales deben estar entre 1 y 5");
  return decimals;
}

function validateLevels(direction, entry, stopLoss, takeProfit, volume) {
  if (![entry, stopLoss, takeProfit].every((value) => Number.isFinite(value) && value > 0)) throw new Error("Entrada, SL y TP deben ser números válidos");
  if (volume !== null && (!Number.isFinite(volume) || volume <= 0)) throw new Error("El volumen debe ser mayor que cero");
  if (direction === "BUY" && !(stopLoss < entry && entry < takeProfit)) throw new Error("BUY requiere SL < entrada < TP");
  if (direction === "SELL" && !(takeProfit < entry && entry < stopLoss)) throw new Error("SELL requiere TP < entrada < SL");
}

function mutateMonitor(state, tradeId, input, timestamp = new Date().toISOString()) {
  state.monitors ||= {};
  const existing = state.monitors[tradeId];
  const action = monitorAction(input);
  if (action === "pause") {
    if (!existing) throw new Error("El seguimiento no existe");
    state.monitors[tradeId] = {...existing, enabled:false, status:"paused", disabled_at:timestamp};
    event(state, "warning", `⏸️ Seguimiento pausado: ${existing.asset || tradeId}`);
    return "paused";
  }
  if (action === "resume") {
    if (!existing) throw new Error("El seguimiento no existe");
    const entry = Number(existing.entry), stopLoss = Number(existing.current_sl ?? existing.stop_loss);
    const takeProfit = Number(existing.current_tp ?? existing.take_profit);
    const volume = existing.volume === null || existing.volume === undefined || existing.volume === "" ? null : Number(existing.volume);
    validateLevels(existing.direction, entry, stopLoss, takeProfit, volume);
    state.monitors[tradeId] = {
      ...existing, activation_id:crypto.randomUUID(), enabled:true, status:"active",
      current_sl:stopLoss, current_tp:takeProfit, volume,
      display_decimals:validDisplayDecimals(existing.display_decimals),
      resumed_at:timestamp, disabled_at:null,
    };
    event(state, "success", `▶️ Seguimiento reanudado: ${existing.asset || tradeId}`);
    return "active";
  }
  if (action !== "activate") throw new Error("Acción de seguimiento no válida");
  const card = (state.session?.cards || []).find((item) => item.id === tradeId);
  if (!card || !card.monitorable) throw new Error("Este trade no está disponible para seguimiento");
  const entry = Number(input.entry), stopLoss = Number(input.stop_loss), takeProfit = Number(input.take_profit);
  const volume = input.volume === null || input.volume === undefined || input.volume === "" ? null : Number(input.volume);
  validateLevels(card.direction, entry, stopLoss, takeProfit, volume);
  state.monitors[tradeId] = {
    ...(existing || {}), trade_id:tradeId, activation_id:crypto.randomUUID(), enabled:true, status:"active",
    asset:card.asset, direction:card.direction, order_type:card.order_type,
    entry, stop_loss:stopLoss, original_sl:stopLoss, current_sl:stopLoss,
    take_profit:takeProfit, original_tp:takeProfit, current_tp:takeProfit,
    volume, display_decimals:validDisplayDecimals(input.display_decimals),
    valid_until:card.valid_until, proxy_symbol:card.proxy_symbol,
    provider:card.provider, source:card.source, session_run_id:state.session?.run_id,
    session_date:state.session?.date, session_generated_at:state.session?.generated_at,
    activated_at:timestamp, history:existing?.history || [], last_decision:null,
  };
  event(state, "success", `📡 Seguimiento activado: ${card.asset} ${card.direction}`);
  return "active";
}

function deleteMonitor(state, tradeId) {
  state.monitors ||= {};
  const existing = state.monitors[tradeId];
  if (!existing) throw new Error("El seguimiento no existe");
  if (existing.enabled) throw new Error("Pausa el seguimiento antes de eliminarlo");
  delete state.monitors[tradeId];
  event(state, "warning", `🗑️ Seguimiento eliminado: ${existing.asset || tradeId}`);
}

async function body(request) {
  try { return await request.json(); } catch { return {}; }
}

async function handle(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS") return response(request, env, {}, 204);
  if (url.pathname === "/health") return response(request, env, {status:"ok"});
  if (url.pathname === "/auth" && request.method === "POST") {
    const input = await body(request);
    if (!env.APP_PIN || !env.APP_SESSION_SECRET) return response(request, env, {error:"Worker authentication is not configured"}, 503);
    if (!constantTimeEqual(input.pin || "", env.APP_PIN)) return response(request, env, {error:"PIN incorrecto"}, 401);
    return response(request, env, {token:await issueToken(env), expires_in:12 * 3600});
  }
  if (!(await verifyToken(request, env))) return response(request, env, {error:"Sesión no autorizada o vencida"}, 401);
  if (url.pathname === "/state" && request.method === "GET") return response(request, env, (await readState(env)).state);

  if (url.pathname === "/sessions" && request.method === "POST") {
    const requestId = crypto.randomUUID();
    await updateState(env, "runtime: queue session", (state) => {
      const status = state.session?.status;
      const since = Date.parse(state.session?.started_at || state.session?.requested_at || "");
      const ageMinutes = Number.isFinite(since) ? (Date.now() - since) / 60000 : Number.POSITIVE_INFINITY;
      if (status === "queued" && ageMinutes < 15) throw new Error("Ya existe una sesión en cola");
      if (status === "running" && ageMinutes < 45) throw new Error("Ya existe una sesión en curso");
      if (["queued","running"].includes(status)) event(state, "warning", "♻️ La sesión anterior quedó vencida; se inicia un nuevo intento");
      state.session = {...(state.session || {}), status:"queued", request_id:requestId, requested_at:new Date().toISOString()};
      event(state, "info", "⏳ Nueva sesión enviada a la cola");
    });
    try {
      await dispatch(env, "new_session", {request_id:requestId});
    } catch (error) {
      await updateState(env, "runtime: session dispatch failed", (state) => {
        state.session = {...state.session, status:"failed", error:error.message};
        event(state, "error", `❌ No se pudo iniciar la sesión: ${error.message}`);
      });
      throw error;
    }
    return response(request, env, {status:"queued", request_id:requestId}, 202);
  }

  const monitorMatch = url.pathname.match(/^\/monitors\/([^/]+)$/);
  if (monitorMatch && request.method === "DELETE") {
    const tradeId = decodeURIComponent(monitorMatch[1]);
    await updateState(env, "runtime: monitor deleted", (current) => deleteMonitor(current, tradeId));
    return response(request, env, {status:"deleted", trade_id:tradeId});
  }
  if (monitorMatch && request.method === "PUT") {
    const tradeId = decodeURIComponent(monitorMatch[1]);
    const input = await body(request);
    const action = monitorAction(input);
    let status = "paused";
    const state = await updateState(env, `runtime: monitor ${action}`, (current) => { status = mutateMonitor(current, tradeId, input); });
    if (status === "active") await dispatch(env, "monitor_tick", {trade_id:tradeId, reason:action});
    return response(request, env, {status, monitor:state.monitors[tradeId]});
  }
  return response(request, env, {error:"Ruta no encontrada"}, 404);
}

export default {
  async fetch(request, env) {
    try { return await handle(request, env); }
    catch (error) { return response(request, env, {error:error.message || "Error interno"}, /Ya existe|no está disponible|no existe|requiere|debe(?:n)?|Pausa|no válida|decimales/.test(error.message) ? 409 : 500); }
  },
  async scheduled(_controller, env, context) {
    context.waitUntil((async () => {
      const {state} = await readState(env);
      if (Object.values(state.monitors || {}).some((item) => item.enabled)) await dispatch(env, "monitor_tick", {reason:"scheduled"});
    })());
  },
};

export {constantTimeEqual, issueToken, verifyToken, mutateMonitor, deleteMonitor};
