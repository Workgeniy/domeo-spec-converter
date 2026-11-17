// popup.js — настройка порта приложения и проверка связи.
const portEl = document.getElementById("port");
const statusEl = document.getElementById("status");

chrome.storage.local.get("port").then(({ port }) => {
  if (port) portEl.value = port;
  check();
});

document.getElementById("save").onclick = async () => {
  await chrome.storage.local.set({ port: parseInt(portEl.value, 10) || 8777 });
  check();
};

async function check() {
  statusEl.textContent = "проверка…";
  try {
    const r = await chrome.runtime.sendMessage({ action: "ping" });
    statusEl.innerHTML = r && r.ok
      ? '<span class="ok">приложение на связи ✓</span>'
      : '<span class="no">приложение не отвечает</span>';
  } catch (e) {
    statusEl.innerHTML = '<span class="no">приложение не отвечает</span>';
  }
}
