const fields = {
  serverUrl: document.querySelector("#serverUrl"),
  apiKey: document.querySelector("#apiKey"),
  label: document.querySelector("#label"),
  status: document.querySelector("#status"),
  save: document.querySelector("#save"),
  toggle: document.querySelector("#toggle"),
  message: document.querySelector("#message"),
};

async function loadState() {
  const state = await chrome.storage.local.get({
    serverUrl: "",
    apiKey: "",
    label: "",
    enabled: false,
    browserId: "",
    lastError: "",
  });
  fields.serverUrl.value = state.serverUrl;
  fields.apiKey.value = state.apiKey;
  fields.label.value = state.label;
  renderState(state);
}

function renderState(state) {
  fields.status.textContent = state.enabled ? "On" : "Off";
  fields.status.classList.toggle("on", Boolean(state.enabled));
  fields.toggle.textContent = state.enabled ? "Turn off" : "Turn on";
  fields.toggle.classList.toggle("primary", !state.enabled);
  fields.message.textContent = state.lastError || (state.enabled ? "Bridge active." : "");
}

async function saveSettings(extra = {}) {
  const serverUrl = fields.serverUrl.value.trim().replace(/\/+$/, "");
  const apiKey = fields.apiKey.value.trim();
  const label = fields.label.value.trim() || "Chrome";
  await chrome.storage.local.set({ serverUrl, apiKey, label, lastError: "", ...extra });
  await chrome.runtime.sendMessage({ type: "codex-lb-debug-config-updated" });
  await loadState();
}

fields.save.addEventListener("click", () => {
  saveSettings().catch((error) => {
    fields.message.textContent = error instanceof Error ? error.message : String(error);
  });
});

fields.toggle.addEventListener("click", async () => {
  const state = await chrome.storage.local.get({ enabled: false });
  await saveSettings({ enabled: !state.enabled });
});

loadState().catch((error) => {
  fields.message.textContent = error instanceof Error ? error.message : String(error);
});
