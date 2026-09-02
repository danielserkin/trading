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
  monitorTab: "active",
};

function escapeHtml(value) {
  return String(value ?? "—").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

function formatNumber(value, decimals = 4, trim = true) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" && !Number.isFinite(Number(value))) return value;
  const number = Number(value);
  const formatted = number.toFixed(decimals);
  return trim ? formatted.replace(/0+$/, "").replace(/\.$/, "") : formatted;
}

function precisionKey(card) {
  if (typeof card === "object" && card) return String(card.id || card.asset || "default");
  return String(card || "default");
}

function displayDecimals(card) {
  const stored = Number(storage.get(`decimals:${precisionKey(card)}`));
  return Number.isInteger(stored) && stored >= 1 && stored <= 5 ? stored : 3;
}

function setDisplayDecimals(card, decimals) {
  storage.set(`decimals:${precisionKey(card)}`, String(decimals));
}

function formatPrice(value, decimals) {
  return formatNumber(value, decimals, false);
}

function exactNumber(value) {
  return formatNumber(value, 8, true);
}

function roundedTrade(card, decimals) {
  const entry = Number(Number(card.entry).toFixed(decimals));
  const stop = Number(Number(card.stop_loss).toFixed(decimals));
  const target = Number(Number(card.take_profit).toFixed(decimals));
  const structure = card.direction === "BUY" ? stop < entry && entry < target : target < entry && entry < stop;
  const risk = card.direction === "BUY" ? entry - stop : stop - entry;
  const reward = card.direction === "BUY" ? target - entry : entry - target;
  const roundedRr = risk > 0 && reward > 0 ? reward / risk : 0;
  const originalRr = Number(card.risk_reward || 0);
  const rrSafe = !originalRr || Math.abs(roundedRr - originalRr) / originalRr <= 0.05;
  return {structure, rrSafe, safe:structure && rrSafe};
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
  const decimals = displayDecimals(card);
  const precision = roundedTrade(card, decimals);
  const priceLevels = [["Entrada","entry",card.entry],["Stop loss","stop_loss",card.stop_loss],["Take profit","take_profit",card.take_profit]];
  const options = [1,2,3,4,5].map((value) => `<option value="${value}" ${value === decimals ? "selected" : ""}>${value}</option>`).join("");
  return `<article class="trade-card ${type}">
    <div class="card-top"><span class="rank">OPORTUNIDAD ${card.rank}</span><span class="stars">${"★".repeat(card.stars || 0)}${"☆".repeat(5-(card.stars || 0))}</span></div>
    <div class="card-title"><h3>${escapeHtml(card.asset)}</h3><span class="direction">${card.direction === "BUY" ? "▲ BUY" : "▼ SELL"}</span></div>
    <p class="order-type">${escapeHtml(card.order_type)} · ${escapeHtml(card.source || "análisis técnico")}</p>
    <label class="precision-control">Decimales <select class="precision-select" data-precision-card="${escapeHtml(card.id)}">${options}</select></label>
    ${precision.safe ? "" : `<p class="precision-warning">⚠️ Esta precisión altera los niveles; al copiar se usará el valor exacto.</p>`}
    <div class="levels">${priceLevels.map(([label,field,value]) => {
      const formatted = formatPrice(value, decimals);
      return `<div class="level"><small>${label}</small><div class="copy-row"><code>${escapeHtml(formatted)}</code><button class="copy-button copy-price-button" data-price-card="${escapeHtml(card.id)}" data-price-field="${field}" title="Copiar">📋</button></div></div>`;
    }).join("")}<div class="level"><small>Tamaño</small><div class="copy-row"><code>${escapeHtml(card.size || "—")}</code><button class="copy-button" data-copy="${escapeHtml(card.size || "")}" title="Copiar">📋</button></div></div></div>
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
  const paused = Object.values(monitors || {}).filter((item) => !item.enabled && item.status === "paused");
  $("#monitor-count").textContent = active.length;
  $("#monitor-tabs").innerHTML = `<button class="monitor-tab ${app.monitorTab === "active" ? "selected" : ""}" data-monitor-tab="active">Activos ${active.length}</button><button class="monitor-tab ${app.monitorTab === "paused" ? "selected" : ""}" data-monitor-tab="paused">Pausados ${paused.length}</button>`;
  const visible = app.monitorTab === "paused" ? paused : active;
  $("#monitor-list").innerHTML = visible.length ? visible.map((item) => {
    const decision = item.last_decision || {};
    const suggested = decision.new_sl != null ? ["Nuevo SL", decision.new_sl] : decision.new_tp != null ? ["Nuevo TP", decision.new_tp] : null;
    const history = (item.history || []).slice(-4).reverse();
    const decimals = Number.isInteger(Number(item.display_decimals)) ? Number(item.display_decimals) : displayDecimals(item.trade_id || item.asset);
    const suggestedValue = suggested ? formatPrice(suggested[1], decimals) : null;
    const origin = item.session_date || item.session_run_id || "sesión anterior";
    const actions = item.enabled
      ? `<button class="monitor-icon pause-monitor" data-pause-monitor="${escapeHtml(item.trade_id)}" title="Pausar seguimiento">⏸</button>`
      : `<button class="monitor-icon resume-monitor" data-resume-monitor="${escapeHtml(item.trade_id)}" title="Reanudar seguimiento">▶</button><button class="monitor-icon delete-monitor" data-delete-monitor="${escapeHtml(item.trade_id)}" title="Eliminar seguimiento">🗑</button>`;
    return `<div class="monitor-item ${item.enabled ? "" : "paused"}"><header><strong>${escapeHtml(item.asset)} ${escapeHtml(item.direction)}</strong><div class="monitor-actions"><span class="action">${escapeHtml((item.enabled ? decision.action || "ESPERANDO" : "PAUSADO").replaceAll("_"," "))}</span>${actions}</div></header><small class="monitor-origin">Sesión ${escapeHtml(origin)} · ${decimals} decimales</small><p>${escapeHtml(decision.instruction || "Primera evaluación pendiente")}<br>${decision.evaluated_at ? new Date(decision.evaluated_at).toLocaleString() : ""}</p>${suggested ? `<div class="suggested-level"><small>${suggested[0]}</small><code>${escapeHtml(suggestedValue)}</code><button class="copy-button" data-copy="${escapeHtml(suggestedValue)}" title="Copiar">📋</button></div>` : ""}${history.length > 1 ? `<details class="decision-history"><summary>Historial (${item.history.length})</summary>${history.map((past) => `<div><time>${new Date(past.evaluated_at).toLocaleTimeString()}</time><span>${escapeHtml((past.action || "—").replaceAll("_"," "))}</span><code>${escapeHtml(formatPrice(past.current_price, decimals))}</code></div>`).join("")}</details>` : ""}</div>`;
  }).join("") : `<div class="mini-empty">${app.monitorTab === "paused" ? "No hay seguimientos pausados." : "Activa “Administrar trade” en una card."}</div>`;
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
  const basketRisk = summary.selected_primary_risk_usd;
  const basketCap = summary.max_primary_risk_usd;
  $("#stat-risk").textContent = basketCap != null
    ? `${basketRisk != null ? `$${Number(basketRisk).toFixed(2)}` : "—"} / $${Number(basketCap).toFixed(2)}`
    : (summary.max_risk_usd != null ? `$${summary.max_risk_usd}` : "$20");
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
  $("#monitor-entry").value = exactNumber(card.entry);
  $("#monitor-sl").value = exactNumber(card.stop_loss);
  $("#monitor-tp").value = exactNumber(card.take_profit);
  $("#monitor-volume").value = card.size ? formatNumber(parseFloat(card.size)) : "";
  $("#monitor-confirm").checked = false;
  $("#monitor-error").hidden = true;
  $("#monitor-dialog").showModal();
}

async function pauseMonitor(tradeId) {
  await api(`/monitors/${encodeURIComponent(tradeId)}`, {method:"PUT", body:JSON.stringify({action:"pause"})});
  toast("⏸️ Seguimiento pausado");
  await refresh();
}

async function resumeMonitor(tradeId) {
  await api(`/monitors/${encodeURIComponent(tradeId)}`, {method:"PUT", body:JSON.stringify({action:"resume"})});
  toast("▶️ Seguimiento reanudado");
  app.monitorTab = "active";
  await refresh();
}

async function removeMonitor(tradeId) {
  await api(`/monitors/${encodeURIComponent(tradeId)}`, {method:"DELETE"});
  toast("🗑️ Seguimiento eliminado");
  await refresh();
}

document.addEventListener("click", async (event) => {
  const close = event.target.closest(".dialog-close");
  if (close) close.closest("dialog")?.close();
  const pause = event.target.closest("[data-pause-monitor]");
  if (pause) {
    pause.disabled = true;
    try { await pauseMonitor(pause.dataset.pauseMonitor); }
    catch (error) { toast(`❌ ${error.message}`); pause.disabled = false; }
  }
  const resume = event.target.closest("[data-resume-monitor]");
  if (resume) {
    resume.disabled = true;
    try { await resumeMonitor(resume.dataset.resumeMonitor); }
    catch (error) { toast(`❌ ${error.message}`); resume.disabled = false; }
  }
  const remove = event.target.closest("[data-delete-monitor]");
  if (remove && window.confirm("¿Eliminar definitivamente este seguimiento pausado?")) {
    remove.disabled = true;
    try { await removeMonitor(remove.dataset.deleteMonitor); }
    catch (error) { toast(`❌ ${error.message}`); remove.disabled = false; }
  }
  const tab = event.target.closest("[data-monitor-tab]");
  if (tab) {
    app.monitorTab = tab.dataset.monitorTab;
    renderMonitors(app.state?.monitors || {});
  }
  const priceCopy = event.target.closest("[data-price-card]");
  if (priceCopy) {
    const card = findCard(priceCopy.dataset.priceCard);
    if (card) {
      const decimals = displayDecimals(card);
      const safe = roundedTrade(card, decimals).safe;
      const raw = card[priceCopy.dataset.priceField];
      await navigator.clipboard.writeText(safe ? formatPrice(raw, decimals) : exactNumber(raw));
      toast(safe ? "📋 Copiado" : "⚠️ Se copió el valor exacto porque el redondeo era inseguro");
    }
  }
  const copy = event.target.closest("[data-copy]");
  if (copy) { await navigator.clipboard.writeText(copy.dataset.copy); toast("📋 Copiado"); }
});

document.addEventListener("change", async (event) => {
  const precision = event.target.closest("[data-precision-card]");
  if (precision) {
    const card = findCard(precision.dataset.precisionCard);
    if (card) setDisplayDecimals(card, Number(precision.value));
    renderCards(app.state?.session || {});
    renderMonitors(app.state?.monitors || {});
    return;
  }
  const toggle = event.target.closest(".monitor-toggle");
  if (!toggle) return;
  const card = findCard(toggle.dataset.tradeId);
  if (toggle.checked) { toggle.checked = false; openMonitor(card); }
  else { try { await pauseMonitor(toggle.dataset.tradeId); } catch (error) { toast(`❌ ${error.message}`); await refresh(); } }
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
  const card = findCard(tradeId);
  try {
    await api(`/monitors/${encodeURIComponent(tradeId)}`, {method:"PUT", body:JSON.stringify({
      action:"activate",
      entry:Number($("#monitor-entry").value), stop_loss:Number($("#monitor-sl").value), take_profit:Number($("#monitor-tp").value),
      volume:$("#monitor-volume").value ? Number($("#monitor-volume").value) : null,
      display_decimals:displayDecimals(card),
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
