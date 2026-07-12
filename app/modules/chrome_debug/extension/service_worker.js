let socket = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let targetTimer = null;
let attachedSessions = new Map();

const DEFAULT_STATE = {
  serverUrl: "",
  apiKey: "",
  label: "",
  enabled: false,
  browserId: "",
};

function normalizeServerUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function debuggeeKey(debuggee) {
  return JSON.stringify({
    tabId: debuggee.tabId ?? null,
    extensionId: debuggee.extensionId ?? null,
    targetId: debuggee.targetId ?? null,
  });
}

function targetIdForTarget(target) {
  return String(target.id || target.targetId || target.tabId || "");
}

function debuggeeForTarget(target) {
  if (target.tabId != null) return { tabId: target.tabId };
  if (target.extensionId != null) return { extensionId: target.extensionId };
  return { targetId: target.targetId || target.id };
}

async function getState() {
  const state = await chrome.storage.local.get(DEFAULT_STATE);
  return { ...state, serverUrl: normalizeServerUrl(state.serverUrl) };
}

async function setLastError(message) {
  await chrome.storage.local.set({ lastError: message || "" });
}

async function mintAgentToken(state) {
  const response = await fetch(`${state.serverUrl}/api/chrome-debug/agent-token`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${state.apiKey}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      browserId: state.browserId || null,
      label: state.label || "Chrome",
      userAgent: navigator.userAgent,
      extensionVersion: chrome.runtime.getManifest().version,
    }),
  });
  if (!response.ok) {
    throw new Error(`Codex LB rejected browser registration (${response.status})`);
  }
  const payload = await response.json();
  await chrome.storage.local.set({ browserId: payload.browserId, lastError: "" });
  return payload;
}

function send(payload) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

async function listTargets() {
  const targets = await chrome.debugger.getTargets();
  return targets
    .map((target) => ({
      ...target,
      id: targetIdForTarget(target),
    }))
    .filter((target) => target.id);
}

async function sendTargets() {
  send({ type: "targets", targets: await listTargets() });
}

function controlResponse(id, ok, extra = {}) {
  send({ type: "control_response", id, ok, ...extra });
}

async function handleAttach(message) {
  const targets = await listTargets();
  const target = targets.find((item) => item.id === message.targetId);
  if (!target) throw new Error("Target not found");
  const debuggee = debuggeeForTarget(target);
  await chrome.debugger.attach(debuggee, "1.3");
  attachedSessions.set(message.sessionId, { debuggee, targetId: message.targetId });
  await sendTargets();
}

async function handleDetach(message) {
  const session = attachedSessions.get(message.sessionId);
  if (!session) return;
  attachedSessions.delete(message.sessionId);
  try {
    await chrome.debugger.detach(session.debuggee);
  } catch (_) {
    // Chrome may already have detached the target.
  }
  await sendTargets();
}

async function handleCommand(message) {
  const session = attachedSessions.get(message.sessionId);
  if (!session) throw new Error("Session is not attached");
  const result = await chrome.debugger.sendCommand(session.debuggee, message.method, message.params || {});
  send({
    type: "cdp_response",
    sessionId: message.sessionId,
    requestId: message.requestId,
    ok: true,
    result: result || {},
  });
}

async function handleMessage(event) {
  const message = JSON.parse(event.data);
  try {
    if (message.type === "list_targets") {
      const targets = await listTargets();
      controlResponse(message.id, true, { targets });
      send({ type: "targets", targets });
      return;
    }
    if (message.type === "attach") {
      await handleAttach(message);
      controlResponse(message.id, true);
      return;
    }
    if (message.type === "detach") {
      await handleDetach(message);
      controlResponse(message.id, true);
      return;
    }
    if (message.type === "cdp_command") {
      await handleCommand(message);
    }
  } catch (error) {
    const payload = error instanceof Error ? error.message : String(error);
    if (message.type === "cdp_command") {
      send({
        type: "cdp_response",
        sessionId: message.sessionId,
        requestId: message.requestId,
        ok: false,
        error: { code: -32000, message: payload },
      });
    } else {
      controlResponse(message.id, false, { error: payload });
    }
  }
}

async function detachAll() {
  const sessions = Array.from(attachedSessions.values());
  attachedSessions = new Map();
  await Promise.allSettled(sessions.map((session) => chrome.debugger.detach(session.debuggee)));
}

function clearTimers() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  if (targetTimer) clearInterval(targetTimer);
  heartbeatTimer = null;
  targetTimer = null;
}

async function disconnect() {
  clearTimers();
  if (socket) {
    try {
      socket.close();
    } catch (_) {
      // Ignore close races.
    }
  }
  socket = null;
  await detachAll();
}

async function connect() {
  const state = await getState();
  if (!state.enabled) {
    await disconnect();
    return;
  }
  if (!state.serverUrl || !state.apiKey) {
    await setLastError("Server URL and API key are required.");
    return;
  }
  if (socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(socket.readyState)) return;
  try {
    const token = await mintAgentToken(state);
    socket = new WebSocket(token.websocketUrl);
    socket.addEventListener("open", async () => {
      await setLastError("");
      sendTargets().catch(() => {});
      heartbeatTimer = setInterval(() => send({ type: "heartbeat", t: Date.now() }), 15000);
      targetTimer = setInterval(() => sendTargets().catch(() => {}), 5000);
    });
    socket.addEventListener("message", (event) => {
      handleMessage(event).catch((error) => setLastError(error instanceof Error ? error.message : String(error)));
    });
    socket.addEventListener("close", async () => {
      clearTimers();
      socket = null;
      await detachAll();
      scheduleReconnect();
    });
    socket.addEventListener("error", () => {
      setLastError("WebSocket connection failed.").catch(() => {});
    });
  } catch (error) {
    await setLastError(error instanceof Error ? error.message : String(error));
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect().catch(() => {});
  }, 5000);
}

chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === "codex-lb-debug-config-updated") {
    connect().catch(() => {});
  }
});

chrome.debugger.onEvent.addListener((debuggee, method, params) => {
  const key = debuggeeKey(debuggee);
  for (const [sessionId, session] of attachedSessions.entries()) {
    if (debuggeeKey(session.debuggee) === key) {
      send({ type: "cdp_event", sessionId, method, params: params || {} });
    }
  }
});

chrome.debugger.onDetach.addListener((debuggee, reason) => {
  const key = debuggeeKey(debuggee);
  for (const [sessionId, session] of Array.from(attachedSessions.entries())) {
    if (debuggeeKey(session.debuggee) === key) {
      attachedSessions.delete(sessionId);
      send({ type: "cdp_event", sessionId, method: "Inspector.detached", params: { reason } });
    }
  }
  sendTargets().catch(() => {});
});

connect().catch(() => {});
