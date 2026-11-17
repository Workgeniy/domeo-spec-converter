// background.js — service worker. ЕДИНСТВЕННЫЙ, кто ходит в приложение Domeo.
// Благодаря host_permissions на 127.0.0.1 запросы идут из контекста расширения без
// CORS-ограничений, и трафик к приложению не виден странице маркетплейса.
//
// Устойчивость к обрыву моста: если цена не ушла (приложение/мост недоступны), она кладётся в
// локальный буфер (chrome.storage.domeoOutbox) и досылается при первом же удачном пинге/отправке —
// проход не надо гонять заново, и перезагрузка страницы ничего не теряет.
const DEFAULT_PORT = 8777;
const OUTBOX_MAX = 4000;        // хватит на полный прогон (566×5 ≈ 2830), старые вытесняются

async function base() {
  const { port } = await chrome.storage.local.get("port");
  return "http://127.0.0.1:" + (port || DEFAULT_PORT);
}
async function jget(path) {
  const r = await fetch((await base()) + path);
  if (!r.ok) throw new Error("http " + r.status);
  return r.json();
}
async function jpost(path, body) {
  const r = await fetch((await base()) + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error("http " + r.status);
  return r.json().catch(() => ({}));
}

async function getOutbox() {
  try { const { domeoOutbox } = await chrome.storage.local.get("domeoOutbox"); return Array.isArray(domeoOutbox) ? domeoOutbox : []; }
  catch (e) { return []; }
}
async function bufferPrice(payload) {
  const box = await getOutbox();
  box.push(payload);
  if (box.length > OUTBOX_MAX) box.splice(0, box.length - OUTBOX_MAX);
  try { await chrome.storage.local.set({ domeoOutbox: box }); } catch (e) {}
}
// Досылаем накопленное по одной, по порядку; на первой же ошибке останавливаемся (мост снова лёг) —
// остаток остаётся в буфере до следующего раза.
let flushing = false;
async function flushOutbox() {
  if (flushing) return 0;
  flushing = true;
  try {
    const box = await getOutbox();
    let sent = 0;
    while (box.length) {
      try { await jpost("/ext/price", box[0]); box.shift(); sent++; }
      catch (e) { break; }
    }
    if (sent) { try { await chrome.storage.local.set({ domeoOutbox: box }); } catch (e) {} }
    return sent;
  } finally { flushing = false; }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.action === "ping") {
        const info = await jget("/ext/ping");
        const flushed = await flushOutbox();                 // мост на связи — досылаем накопленное
        const pending = (await getOutbox()).length;
        sendResponse({ ok: true, info, flushed, pending });
      }
      else if (msg.action === "getSpec") {
        // ответ в конверте ApiResponse: { success, data:{ items } }
        const r = await jget("/ext/spec/current");
        sendResponse({ ok: true, items: (r && r.data && r.data.items) || (r && r.items) || [] });
      }
      else if (msg.action === "sendPrice") {
        try {
          const res = await jpost("/ext/price", msg.payload);
          flushOutbox();                                     // заодно подчистим буфер, если был
          sendResponse({ ok: true, res });
        } catch (e) {
          await bufferPrice(msg.payload);                    // мост недоступен — не теряем, в буфер
          sendResponse({ ok: false, buffered: true, pending: (await getOutbox()).length, error: String(e && e.message || e) });
        }
      }
      else if (msg.action === "flush") sendResponse({ ok: true, sent: await flushOutbox(), pending: (await getOutbox()).length });
      else if (msg.action === "pending") sendResponse({ ok: true, pending: (await getOutbox()).length });
      else sendResponse({ ok: false, error: "unknown action" });
    } catch (e) {
      sendResponse({ ok: false, error: String(e && e.message || e) });
    }
  })();
  return true; // ответ асинхронный
});
