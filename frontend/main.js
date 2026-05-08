const gateway = "http://localhost:10000";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const eventTitles = {
  request_success: "Успешный запрос",
  request_failed: "Ошибка запроса",
  circuit_rejected: "Запрос отклонен Circuit Breaker",
  circuit_reset: "Circuit Breaker сброшен",
  fault_configured: "Параметры сбоя изменены",
  direct_gateway_success: "Прямой Envoy-вызов успешен",
  direct_gateway_failed: "Прямой Envoy-вызов получил отказ upstream",
};
const retryNodes = ["retryOne", "retryTwo", "retryThree"];
const flowNodeIds = ["nodeClient", "nodeGateway", "nodeControl", "nodeBreaker", "nodeService"];
const flowEdgeIds = ["edgeClientGateway", "edgeGatewayControl", "edgeControlBreaker", "edgeBreakerService"];
const localGatewayEvents = [];
let latestBreakerSnapshot = null;

function setFlowStatus(message, className = "") {
  const element = $("flowStatus");
  if (!element) return;
  element.textContent = message;
  element.className = `flow-status ${className}`.trim();
}

function resetFlowActivity() {
  [...flowNodeIds, ...flowEdgeIds].forEach((id) => {
    const element = $(id);
    if (element) element.classList.remove("active", "blocked", "bypassed");
  });
}

function renderFailureThreshold(failures, state) {
  const normalizedFailures = Math.min(Number(failures ?? 0), retryNodes.length);

  retryNodes.forEach((id, index) => {
    const element = $(id);
    if (!element) return;
    element.className = "";
    element.classList.add(index < normalizedFailures ? "failed" : "healthy");
  });

  const retryMeta = $("retryMeta");
  if (!retryMeta) return;

  if (state === "OPEN") {
    retryMeta.textContent = "Порог ошибок достигнут: Circuit Breaker открыт";
  } else if (state === "HALF_OPEN") {
    retryMeta.textContent = "Пробный режим: система проверяет, восстановился ли сервис";
  } else if (normalizedFailures === 0) {
    retryMeta.textContent = "Ошибок нет: запросы к unstable-service разрешены";
  } else {
    retryMeta.textContent = `Накоплено ошибок: ${normalizedFailures} из ${retryNodes.length}`;
  }
}

function renderBreakerOnFlow(state) {
  const breakerNode = $("nodeBreaker");
  if (!breakerNode) return;
  breakerNode.classList.remove("closed", "half-open", "open");
  breakerNode.classList.add(String(state).toLowerCase().replace("_", "-"));
  $("flowBreakerState").textContent = state;
}

function renderProtectedFlow(payload) {
  resetFlowActivity();
  ["nodeClient", "nodeGateway", "nodeControl", "nodeBreaker"].forEach((id) =>
    $(id).classList.add("active"),
  );
  ["edgeClientGateway", "edgeGatewayControl", "edgeControlBreaker"].forEach((id) =>
    $(id).classList.add("active"),
  );

  const attempts = Number(payload.attempts ?? 0);
  const blockedByBreaker = attempts === 0 || payload.event_type === "circuit_rejected";
  const failed = !payload.ok;

  if (blockedByBreaker) {
    $("edgeBreakerService").classList.add("blocked");
    $("nodeService").classList.add("blocked");
    setFlowStatus("Breaker открыт: запрос остановлен до unstable-service", "danger");
    return;
  }

  $("edgeBreakerService").classList.add("active");
  $("nodeService").classList.add("active");
  setFlowStatus(
    failed ? "Запрос дошел до сервиса, retry не помог" : "Запрос успешно прошел до сервиса",
    failed ? "danger" : "ok",
  );
}

function renderDirectFlow(payload) {
  resetFlowActivity();
  ["nodeClient", "nodeGateway", "nodeService"].forEach((id) => $(id).classList.add("active"));
  ["nodeControl", "nodeBreaker"].forEach((id) => $(id).classList.add("bypassed"));
  $("edgeClientGateway").classList.add("active");
  const retryMeta = $("retryMeta");
  if (retryMeta) {
    retryMeta.textContent =
      "Прямой маршрут не использует прикладной Circuit Breaker из control-api";
  }
  const failed = payload && !payload.ok;
  setFlowStatus(
    failed
      ? `Прямой вызов через Envoy завершился HTTP ${payload.status_code}`
      : "Прямой вызов: Envoy идет к сервису без контрольного API",
    failed ? "danger" : "ok",
  );
}

function rememberDirectGatewayEvent(payload) {
  localGatewayEvents.unshift({
    id: `direct-${Date.now()}`,
    created_at: new Date().toISOString(),
    service: "unstable-service",
    event_type: payload.ok ? "direct_gateway_success" : "direct_gateway_failed",
    status_code: payload.status_code,
    breaker_state: "BYPASS",
    local: true,
  });
  localGatewayEvents.splice(5);
}

async function request(path, options = {}) {
  const { allowError = false, ...fetchOptions } = options;
  const response = await fetch(`${gateway}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...fetchOptions,
  });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = { raw: text };
  }
  if (allowError) {
    return {
      ok: response.ok,
      status_code: response.status,
      payload,
    };
  }
  if (!response.ok) {
    throw new Error(JSON.stringify(payload, null, 2));
  }
  return payload;
}

function renderJson(payload) {
  $("responseBox").textContent = JSON.stringify(payload, null, 2);
}

function toneForState(state) {
  if (state === "OPEN") return "danger";
  if (state === "HALF_OPEN") return "warning";
  return "ok";
}

function renderBreakerMeta() {
  if (!latestBreakerSnapshot) return;

  const secondsLeft = Math.max(
    0,
    Math.ceil((latestBreakerSnapshot.nextProbeAt - Date.now()) / 1000),
  );
  const failures = latestBreakerSnapshot.failures;

  if (latestBreakerSnapshot.state === "CLOSED") {
    $("breakerMeta").textContent = `${failures} ошибок, запросы разрешены`;
    return;
  }

  $("breakerMeta").textContent = `${failures} ошибок, попытка через ${secondsLeft} с`;
}

async function refreshState() {
  const state = await request("/control/state");
  const breaker = state.breaker;
  const fault = state.fault;

  $("breakerState").textContent = breaker.state;
  $("breakerState").className = toneForState(breaker.state);
  latestBreakerSnapshot = {
    state: breaker.state,
    failures: Number(breaker.failures ?? 0),
    nextProbeAt: Date.now() + Math.max(0, Number(breaker.seconds_until_probe ?? 0)) * 1000,
  };
  renderBreakerMeta();

  $("faultState").textContent = fault.enabled ? "Включен" : "Отключен";
  $("faultState").className = fault.enabled ? "danger" : "ok";
  $("faultMeta").textContent =
    `${Math.round(fault.error_rate * 100)}% ошибок, задержка ${fault.latency_ms} ms`;

  renderBreakerOnFlow(breaker.state);
  renderFailureThreshold(breaker.failures, breaker.state);
}

async function refreshEvents() {
  const events = await request("/control/events?limit=20");
  const visibleEvents = [...localGatewayEvents, ...events].sort(
    (left, right) => new Date(right.created_at) - new Date(left.created_at),
  );
  updateEventStats(visibleEvents);
  $("events").innerHTML = visibleEvents
    .map((event) => {
      const stateClass = toneForState(event.breaker_state);
      const title = eventTitles[event.event_type] ?? event.event_type;
      return `
        <div class="${eventClass(event)}">
          <b>${title} · ${event.service}</b>
          <small>${new Date(event.created_at).toLocaleString()}</small>
          <small>HTTP: ${event.status_code ?? "-"} · Breaker:
            <span class="${stateClass}">${event.breaker_state ?? "-"}</span>
          </small>
          ${eventNote(event)}
        </div>
      `;
    })
    .join("");
}

function eventClass(event) {
  const classes = ["event"];
  if (event.local) classes.push("local-event");
  if (event.event_type === "circuit_rejected") classes.push("rejected-event");
  if (event.event_type === "request_failed") classes.push("failed-event");
  return classes.join(" ");
}

function eventNote(event) {
  if (event.local) {
    return "<small>Маршрут идет напрямую через Envoy, поэтому это событие не пишется в PostgreSQL control-api.</small>";
  }
  if (event.event_type === "circuit_rejected") {
    return "<small>Событие записано control-api в PostgreSQL: Circuit Breaker остановил запрос до обращения к unstable-service.</small>";
  }
  if (event.event_type === "request_failed") {
    return "<small>Событие записано control-api в PostgreSQL: upstream вернул отказ после внутренних retry.</small>";
  }
  return "";
}

function updateEventStats(events) {
  const success = events.filter((event) => event.event_type === "request_success").length;
  const failures = events.filter((event) =>
    ["request_failed", "circuit_rejected", "direct_gateway_failed"].includes(event.event_type),
  ).length;
  $("eventStats").textContent = `${success} / ${failures}`;
  $("eventStatsMeta").textContent = "успехи / отказы";
}

async function runAction(action) {
  try {
    const payload = await action();
    renderJson(payload);
    await refreshState();
    await refreshEvents();
    return payload;
  } catch (error) {
    renderJson({ error: error.message });
  }
}

async function configureFault(enabled) {
  return request("/control/faults/unstable-service", {
    method: "POST",
    body: JSON.stringify({
      enabled,
      error_rate: enabled ? 1 : 0,
      latency_ms: enabled ? 150 : 0,
    }),
  });
}

async function protectedCall() {
  const payload = await request("/protected/unstable");
  $("lastStatus").textContent = payload.ok ? "Успех" : "Отказ";
  $("lastStatus").className = payload.ok ? "ok" : "danger";
  $("lastMeta").textContent = `${payload.attempts} внутренних попыток, HTTP ${payload.status_code}`;
  renderProtectedFlow(payload);
  return payload;
}

$("sendProtected").addEventListener("click", async () => {
  await runAction(async () => protectedCall());
});

$("sendDirect").addEventListener("click", async () => {
  await runAction(async () => {
    const payload = await request("/api/unstable", { allowError: true });
    $("lastStatus").textContent = payload.ok ? "Успех" : "Отказ";
    $("lastStatus").className = payload.ok ? "ok" : "danger";
    $("lastMeta").textContent = `Прямой Envoy, HTTP ${payload.status_code}`;
    rememberDirectGatewayEvent(payload);
    renderDirectFlow(payload);
    return payload;
  });
});

$("enableFault").addEventListener("click", async () => {
  await runAction(async () => configureFault(true));
});

$("disableFault").addEventListener("click", async () => {
  await runAction(async () => configureFault(false));
});

$("resetCircuit").addEventListener("click", async () => {
  await runAction(async () => request("/control/circuit/reset", { method: "POST" }));
});

$("runScenario").addEventListener("click", async () => {
  const button = $("runScenario");
  button.disabled = true;
  button.textContent = "Сценарий выполняется...";
  try {
    await runAction(async () => {
      resetFlowActivity();
      setFlowStatus("Сценарий запущен: сбрасываем breaker", "ok");
      await request("/control/circuit/reset", { method: "POST" });
      await refreshState();
      await configureFault(false);
      const normal = await protectedCall();
      await refreshState();
      await configureFault(true);
      const failedCalls = [];
      for (let index = 0; index < 4; index += 1) {
        failedCalls.push(await protectedCall());
        await refreshState();
        await sleep(300);
      }
      return {
        scenario: "normal -> fault -> Retry -> Circuit Breaker OPEN",
        normal,
        failedCalls,
      };
    });
  } finally {
    button.disabled = false;
    button.textContent = "Запустить сценарий сбоя";
  }
});

$("refreshEvents").addEventListener("click", refreshEvents);

setInterval(() => {
  refreshState().catch(() => {});
}, 3000);

setInterval(renderBreakerMeta, 1000);

refreshState().catch((error) => renderJson({ error: error.message }));
refreshEvents().catch(() => {});
