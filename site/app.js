const $ = (selector) => document.querySelector(selector);
const storage = {
  get: (key) => localStorage.getItem(`trading-control:${key}`),
  set: (key, value) => localStorage.setItem(`trading-control:${key}`, value),
};

const app = {
  api: storage.get("api") || window.TRADING_API_BASE || "",
  token: storage.get("token") || "",
  state: null,
  timer: null,
};

function escapeHtml(value) {
  return String(value ?? "—").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" && !Number.isFinite(Number(value))) return value;
  const number = Number(value);
  return number.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  setTimeout(() => element.classList.remove("show"), 2200);
}

async function api(path, options = {}) {
  if (!app.api) throw new Error("Configura la URL del Worker");
  const response = await fetch(`${app.api.replace(/\/$/, "")}${path}`, {
    ...options,
    headers: {"Content-Type":"application/json", ...(app.token ? {Authorization:`Bearer ${app.token}`} : {}), ...(options.headers || {})},
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Error HTTP ${response.status}`);
  return payload;
}

function connection(online, label) {
  const pill = $("#connection-pill");
  pill.className = `pill ${online ? "pill-online" : "pill-offline"}`;
  pill.setAttribute("aria-label", label);
  pill.innerHTML = `<i></i><span class="pill-label">${escapeHtml(label)}</span>`;
  $("#new-session-button").disabled = !online;
}

async function connect(workerUrl, pin) {
  app.api = workerUrl.replace(/\/$/, "");
  const payload = await api("/auth", {method:"POST", body:JSON.stringify({pin})});
  app.token = payload.token;
  storage.set("api", app.api);
  storage.set("token", app.token);
  connection(true, "Conectado");
  await refresh();
}

async function refresh() {
  if (!app.api || !app.token) return;
  try {
    app.state = await api("/state");
    connection(true, "Conectado");
    render();
  } catch (error) {
    if (/401|token|sesión|autoriz/i.test(error.message)) {
      app.token = "";
      storage.set("token", "");
      connection(false, "Sesión vencida");
      $("#settings-dialog").showModal();
    } else {
      connection(false, "Sin conexión");
    }
  }
}

function statusInfo(status) {
  return {
    idle:["Sin sesión","neutral"], queued:["En cola","running"], running:["Analizando","running"],
    completed:["Completada","success"], failed:["Fallida","error"],
  }[status] || [status || "Sin sesión", "neutral"];
}

function cardHtml(card) {
  if (card.status === "NO_TRADE") {
    return `<article class="trade-card wait"><div class="card-top"><span class="rank">SLOT ${card.rank}</span></div><div class="card-title"><h3>NO TRADE</h3><span class="direction">ESPERAR</span></div><p class="order-type">${escapeHtml((card.reasons || [])[0])}</p><div class="monitor-control"><div class="monitor-label"><strong>Sin entrada</strong><small>No se inventaron niveles.</small></div></div></article>`;
  }
  const type = card.direction === "SELL" ? "sell" : "buy";
  const active = Boolean(app.state?.monitors?.[card.id]?.enabled);
  const levels = [["Entrada",card.entry],["Stop loss",card.stop_loss],["Take profit",card.take_profit],["Tamaño",card.size]];
  return `<article class="trade-card ${type}">
    <div class="card-top"><span class="rank">OPORTUNIDAD ${card.rank}</span><span class="stars">${"★".repeat(card.stars || 0)}${"☆".repeat(5-(card.stars || 0))}</span></div>
    <div class="card-title"><h3>${escapeHtml(card.asset)}</h3><span class="direction">${card.direction === "BUY" ? "▲ BUY" : "▼ SELL"}</span></div>
    <p class="order-type">${escapeHtml(card.order_type)} · ${escapeHtml(card.source || "análisis técnico")}</p>
    <div class="levels">${levels.map(([label,value]) => {
      const formatted = formatNumber(value);
      return `<div class="level"><small>${label}</small><div class="copy-row"><code>${escapeHtml(formatted)}</code><button class="copy-button" data-copy="${escapeHtml(formatted)}" title="Copiar">📋</button></div></div>`;
    }).join("")}</div>
    <div class="card-facts"><span>⚖️ R/R <strong>${escapeHtml(card.risk_reward?.toFixed?.(2) || "—")}</strong></span><span>🛡️ Riesgo <strong>${card.risk_usd != null ? `$${Number(card.risk_usd).toFixed(2)}` : "—"}</strong></span></div>
    <div class="monitor-control"><div class="monitor-label"><strong>📡 Administrar trade</strong><small>${active ? "Seguimiento activo" : "Evaluar cada 15 minutos"}</small></div><label class="switch"><input class="monitor-toggle" data-trade-id="${escapeHtml(card.id)}" type="checkbox" ${active ? "checked" : ""} ${card.monitorable ? "" : "disabled"}><span class="slider"></span></label></div>
  </article>`;
}

function renderCards(session) {
  const cards = session.cards || [];
  $("#cards").innerHTML = cards.length ? cards.map(cardHtml).join("") : `<div class="empty-state"><span>📊</span><h3>Todo listo para comenzar</h3><p>Pulsa “Nueva sesión” para generar tus próximas oportunidades.</p></div>`;
}

function renderMonitors(monitors) {
  const active = Object.values(monitors || {}).filter((item) => item.enabled);
  $("#monitor-count").textContent = active.length;
  $("#monitor-list").innerHTML = active.length ? active.map((item) => {
    const decision = item.last_decision || {};
    const suggested = decision.new_sl != null ? ["Nuevo SL", decision.new_sl] : decision.new_tp != null ? ["Nuevo TP", decision.new_tp] : null;
    const history = (item.history || []).slice(-4).reverse();
    const suggestedValue = suggested ? formatNumber(suggested[1]) : null;
    return `<div class="monitor-item"><header><strong>${escapeHtml(item.asset)} ${escapeHtml(item.direction)}</strong><div class="monitor-actions"><span class="action">${escapeHtml((decision.action || "ESPERANDO").replaceAll("_"," "))}</span><button class="stop-monitor" data-stop-monitor="${escapeHtml(item.trade_id)}" title="Detener seguimiento">⏹</button></div></header><p>${escapeHtml(decision.instruction || "Primera evaluación pendiente")}<br>${decision.evaluated_at ? new Date(decision.evaluated_at).toLocaleString() : ""}</p>${suggested ? `<div class="suggested-level"><small>${suggested[0]}</small><code>${escapeHtml(suggestedValue)}</code><button class="copy-button" data-copy="${escapeHtml(suggestedValue)}" title="Copiar">📋</button></div>` : ""}${history.length > 1 ? `<details class="decision-history"><summary>Historial (${item.history.length})</summary>${history.map((past) => `<div><time>${new Date(past.evaluated_at).toLocaleTimeString()}</time><span>${escapeHtml((past.action || "—").replaceAll("_"," "))}</span><code>${escapeHtml(formatNumber(past.current_price))}</code></div>`).join("")}</details>` : ""}</div>`;
  }).join("") : `<div class="mini-empty">Activa “Administrar trade” en una card.</div>`;
}

function renderEvents(events) {
  const terminal = $("#terminal");
  const hiddenBefore = Number(sessionStorage.getItem("trading-control:hide-events-before") || 0);
  const visible = (events || []).filter((event) => new Date(event.at).getTime() >= hiddenBefore);
  terminal.innerHTML = visible.length ? visible.map((event) => `<p class="${escapeHtml(event.level || "")}"><time>${new Date(event.at).toLocaleTimeString()}</time>${escapeHtml(event.message)}</p>`).join("") : `<p class="muted"><time>--:--:--</time>Sin actividad reciente.</p>`;
  terminal.scrollTop = terminal.scrollHeight;
}

function render() {
  const state = app.state || {};
  const session = state.session || {};
  const summary = session.summary || {};
  $("#stat-messages").textContent = summary.messages_reviewed ?? "—";
  $("#stat-symbols").textContent = summary.symbols_scanned ?? "—";
  $("#stat-valid").textContent = summary.valid_candidates ?? "—";
  $("#stat-risk").textContent = summary.max_risk_usd != null ? `$${summary.max_risk_usd}` : "$20";
  const [label, css] = statusInfo(session.status);
  $("#session-status").textContent = label;
  $("#session-status").className = `status-badge ${css}`;
  $("#session-time").textContent = session.generated_at ? new Date(session.generated_at).toLocaleString() : "—";
  $("#new-session-button").disabled = !app.token || ["queued","running"].includes(session.status);
  renderCards(session);
  renderMonitors(state.monitors);
  renderEvents(state.events);
}

async function newSession() {
  const button = $("#new-session-button");
  button.disabled = true;
  try {
    await api("/sessions", {method:"POST", body:"{}"});
    toast("🚀 Sesión enviada a GitHub Actions");
    await refresh();
  } catch (error) { toast(`❌ ${error.message}`); button.disabled = false; }
}

function findCard(tradeId) { return (app.state?.session?.cards || []).find((card) => card.id === tradeId); }

function openMonitor(card) {
  $("#monitor-trade-id").value = card.id;
  $("#monitor-dialog-title").textContent = `${card.asset} ${card.direction}`;
  $("#monitor-entry").value = formatNumber(card.entry);
  $("#monitor-sl").value = formatNumber(card.stop_loss);
  $("#monitor-tp").value = formatNumber(card.take_profit);
  $("#monitor-volume").value = card.size ? formatNumber(parseFloat(card.size)) : "";
  $("#monitor-confirm").checked = false;
  $("#monitor-error").hidden = true;
  $("#monitor-dialog").showModal();
}

async function disableMonitor(tradeId) {
  await api(`/monitors/${encodeURIComponent(tradeId)}`, {method:"PUT", body:JSON.stringify({enabled:false})});
  toast("⏸️ Seguimiento desactivado");
  await refresh();
}

document.addEventListener("click", async (event) => {
  const close = event.target.closest(".dialog-close");
  if (close) close.closest("dialog")?.close();
  const stop = event.target.closest("[data-stop-monitor]");
  if (stop) {
    stop.disabled = true;
    try { await disableMonitor(stop.dataset.stopMonitor); }
    catch (error) { toast(`❌ ${error.message}`); stop.disabled = false; }
  }
  const copy = event.target.closest("[data-copy]");
  if (copy) { await navigator.clipboard.writeText(copy.dataset.copy); toast("📋 Copiado"); }
});

document.addEventListener("change", async (event) => {
  const toggle = event.target.closest(".monitor-toggle");
  if (!toggle) return;
  const card = findCard(toggle.dataset.tradeId);
  if (toggle.checked) { toggle.checked = false; openMonitor(card); }
  else { try { await disableMonitor(toggle.dataset.tradeId); } catch (error) { toast(`❌ ${error.message}`); await refresh(); } }
});

$("#settings-button").addEventListener("click", () => {
  $("#api-url-input").value = app.api;
  $("#settings-dialog").showModal();
});
$("#new-session-button").addEventListener("click", newSession);
$("#clear-local-log").addEventListener("click", () => { sessionStorage.setItem("trading-control:hide-events-before", Date.now()); renderEvents([]); });

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#settings-error");
  error.hidden = true;
  try {
    await connect($("#api-url-input").value.trim(), $("#pin-input").value);
    $("#settings-dialog").close();
    $("#pin-input").value = "";
  } catch (exception) { error.textContent = exception.message; error.hidden = false; }
});

$("#monitor-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#monitor-error");
  error.hidden = true;
  const tradeId = $("#monitor-trade-id").value;
  try {
    await api(`/monitors/${encodeURIComponent(tradeId)}`, {method:"PUT", body:JSON.stringify({
      enabled:true,
      entry:Number($("#monitor-entry").value), stop_loss:Number($("#monitor-sl").value), take_profit:Number($("#monitor-tp").value),
      volume:$("#monitor-volume").value ? Number($("#monitor-volume").value) : null,
    })});
    $("#monitor-dialog").close();
    toast("📡 Seguimiento activado");
    await refresh();
  } catch (exception) { error.textContent = exception.message; error.hidden = false; }
});

async function initialize() {
  if (!app.api || !app.token) {
    connection(false, "Configurar");
    $("#api-url-input").value = app.api;
    $("#settings-dialog").showModal();
  } else {
    await refresh();
  }
  app.timer = setInterval(refresh, 8000);
}

initialize();
