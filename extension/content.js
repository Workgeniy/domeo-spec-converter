// content.js — панель Domeo на странице маркетплейса. ВЕДЁТ СПЕКА: панель показывает строки
// спецификации (их отдаёт приложение через мост), у каждой кнопка «искать» открывает её поиск на
// выбранном маркетплейсе. Расширение читает выдачу (inject.js) и предлагает цены — ты выбираешь,
// цена уходит в эту строку спеки в Domeo. Один клик = один поиск (антибот не трогаем).
(function () {
  "use strict";
  const TAG = "domeo-mp";
  const seen = new Map();      // articleId -> товар с текущей страницы
  let spec = [];               // строки спеки из моста: [{id,name,qty}]
  let appOk = false;
  let pending = 0;             // сколько найденных цен в буфере (не ушли в мост)
  let ready = false;
  let market = "wildberries";  // выбранный маркетплейс
  let activeId = "";           // id строки, для которой сейчас ищем
  const priced = new Set();    // id строк, по которым уже отправили цену (для ✓)

  // авто-обход: расширение само идёт по строкам спеки — под присмотром, порциями, со стопом на антиботе
  let auto = null;             // {on,market,queue:[{id,name}],pos,batch,porcia,paceMin,paceMax,emptyStreak,specSig}
  let autoCountdown = 0;       // сек до следующей строки (для показа)
  let autoRan = false;         // обработать каждую загрузку страницы один раз
  let autoMsg = "", autoMsgT = null;
  let autoTimer = null, autoInterval = null, autoWaitTimer = null;
  const AUTO_K = 5;            // сколько кандидатов слать в строку
  function autoIsOn() { return !!(auto && auto.on); }

  const MARKETS = {
    wildberries:    { name: "Wildberries",    ready: true,  url: (q) => "https://www.wildberries.ru/catalog/0/search.aspx?search=" + encodeURIComponent(q) },
    dns:            { name: "DNS",             ready: true,  url: (q) => "https://www.dns-shop.ru/search/?q=" + encodeURIComponent(q) },
    citilink:       { name: "Ситилинк",        ready: true,  url: (q) => "https://www.citilink.ru/search/?text=" + encodeURIComponent(q) },
    ozon:           { name: "Ozon",            ready: true,  url: (q) => "https://www.ozon.ru/search/?text=" + encodeURIComponent(q) },
    yandexmarket:   { name: "Я.Маркет",        ready: false, url: (q) => "https://market.yandex.ru/search?text=" + encodeURIComponent(q) },
    megamarket:     { name: "Мегамаркет",      ready: false, url: (q) => "https://megamarket.ru/catalog/?q=" + encodeURIComponent(q) },
    vseinstrumenti: { name: "ВсеИнструменти",  ready: false, url: (q) => "https://www.vseinstrumenti.ru/search/?what=" + encodeURIComponent(q) },
    lemana:         { name: "Лемана ПРО",      ready: false, url: (q) => "https://lemanapro.ru/search/?q=" + encodeURIComponent(q) },
    petrovich:      { name: "Петрович",        ready: false, url: (q) => "https://petrovich.ru/search/?q=" + encodeURIComponent(q) }
  };

  function marketFromHost() {
    const h = location.host;
    if (/wildberries\.ru/.test(h)) return "wildberries";
    if (/lemanapro\.ru|leroymerlin\.ru/.test(h)) return "lemana";
    for (const k of Object.keys(MARKETS)) if (h.includes(k)) return k;
    return null;
  }

  // строку для поиска чистим от ведущего номера позиции («2.10 Смеситель» → «Смеситель»)
  function cleanQuery(name) {
    return String(name).replace(/^\d+(?:[.\-]\d+)*\s+/, "").trim() || String(name);
  }

  // ---- чтение выдачи из DOM ----
  // Надёжнее перехвата fetch: WB грузит выдачу из веб-воркера, мимо window.fetch (inject её не видит).
  // Карточки уже в DOM — читаем их. Добавить сайт = свой scrapeX + строка в DOM_SCRAPERS.
  function priceFirst(s) { const m = String(s == null ? "" : s).match(/(\d[\d\s ]*)\s*₽/); return m ? parseInt(m[1].replace(/\D/g, ""), 10) : null; }
  function scrapeWb() {
    const items = [];
    for (const card of document.querySelectorAll("article[data-nm-id]")) {
      const id = card.getAttribute("data-nm-id"); if (!id) continue;
      const link = card.querySelector('a[href*="detail.aspx"]');
      const name = ((link && (link.getAttribute("aria-label") || link.textContent)) || "").replace(/\s+/g, " ").trim();
      const ins = card.querySelector("ins"), del = card.querySelector("del"), box = card.querySelector('[class*="price"]');
      const price = priceFirst(ins ? ins.textContent : (box ? box.textContent : ""));
      const oldPrice = priceFirst(del ? del.textContent : "");
      if (!price || !name) continue;
      let url = link ? link.getAttribute("href") : "";
      if (url && !/^https?:/i.test(url)) url = "https://www.wildberries.ru/" + url.replace(/^\/+/, "");
      items.push({ source: "wildberries", articleId: String(id), name: name, brand: "", seller: "", price: price, oldPrice: oldPrice || null, rating: null, reviews: null, url: url || ("https://www.wildberries.ru/catalog/" + id + "/detail.aspx") });
    }
    return items;
  }
  // Ozon: карточка .tile-root, артикул — хвостовое число ссылки /product/…-<id>/; цена = первый ₽-спан,
  // старая = максимальный ₽ (у Ozon зачёркнутая выше), имя = самый длинный спан без ₽ и служебных слов.
  const OZON_SKIP = /осталось|отзыв|продаж|рейтинг|кешбэк|бонус|рассрочк|%|проверен|доставк|налич|в корзин|сравнит/i;
  function scrapeOzon() {
    const items = [], ids = new Set();
    for (const tile of document.querySelectorAll(".tile-root")) {
      const link = tile.querySelector('a[href*="/product/"]');
      if (!link) continue;
      const href = (link.getAttribute("href") || "").split("?")[0];
      const m = href.match(/(\d+)\/?$/);
      const id = m ? m[1] : "";
      if (!id || ids.has(id)) continue;
      const spans = [...tile.querySelectorAll("span")].map((s) => s.textContent.replace(/\s+/g, " ").trim()).filter(Boolean);
      const priceSpans = spans.filter((x) => /₽/.test(x) && !/мес/i.test(x));
      const nums = priceSpans.map(priceFirst).filter(Boolean);
      if (!nums.length) continue;
      const price = priceFirst(priceSpans[0]);
      const maxN = Math.max.apply(null, nums);
      const oldPrice = maxN > price ? maxN : null;
      const name = spans.filter((x) => !/₽/.test(x) && x.length > 10 && !OZON_SKIP.test(x)).sort((a, b) => b.length - a.length)[0] || "";
      if (!price || !name) continue;
      ids.add(id);
      items.push({ source: "ozon", articleId: String(id), name: name, brand: "", seller: "", price: price, oldPrice: oldPrice, rating: null, reviews: null, url: "https://www.ozon.ru" + href });
    }
    return items;
  }
  const DOM_SCRAPERS = { wildberries: scrapeWb, ozon: scrapeOzon };

  function scrapeNow() {
    const fn = DOM_SCRAPERS[marketFromHost()];
    if (!fn) return;
    let items = []; try { items = fn() || []; } catch (e) { items = []; }
    let added = 0;
    for (const p of items) if (p.articleId && !seen.has(p.articleId)) { seen.set(p.articleId, p); added++; }
    if (added) { if (ready) render(); try { console.log("[domeo] DOM-выдача: +" + added + " (всего " + seen.size + ")"); } catch (e) {} }
  }
  // выдача появляется не сразу — опрашиваем DOM несколько секунд (и ловим под-подгрузку)
  function startScrapePoll() {
    if (!DOM_SCRAPERS[marketFromHost()]) return;
    let tries = 0;
    const iv = setInterval(() => { tries++; scrapeNow(); if (tries > 26) clearInterval(iv); }, 750);
    scrapeNow();
  }

  // 1) перехватчик — в контекст страницы
  try {
    const s = document.createElement("script");
    s.src = chrome.runtime.getURL("inject.js");
    s.onload = () => s.remove();
    (document.head || document.documentElement).appendChild(s);
  } catch (e) {}

  // 2) приём товаров со страницы
  window.addEventListener("message", (e) => {
    if (e.source !== window || !e.data || !e.data[TAG]) return;
    let added = false;
    for (const p of e.data.items) if (p.articleId && !seen.has(p.articleId)) { seen.set(p.articleId, p); added = true; }
    if (added && ready) render();
  });

  function app(action, payload) {
    return new Promise((resolve) => {
      try { chrome.runtime.sendMessage({ action, payload }, (r) => resolve(r || { ok: false })); }
      catch (e) { resolve({ ok: false }); }
    });
  }
  async function refreshApp() {
    const ping = await app("ping");
    appOk = !!(ping && ping.ok);
    const pend = await app("pending");                 // размер буфера — локально, работает и при обрыве
    if (pend && typeof pend.pending === "number") pending = pend.pending;
    if (appOk) { const s = await app("getSpec"); spec = (s && s.ok && s.items) || []; }
    if (ready) render();
  }

  // 3) инициализация: восстановить выбранный маркетплейс и активную строку (переживают навигацию)
  async function init() {
    try {
      const mk = marketFromHost();
      const keys = ["domeoMarket", "domeoActive"];
      if (mk) keys.push("domeoAuto_" + mk);
      const st = await chrome.storage.local.get(keys);
      market = st.domeoMarket || mk || "wildberries";
      if (st.domeoActive && st.domeoActive.id) activeId = st.domeoActive.id;
      auto = (mk && st["domeoAuto_" + mk]) || null;              // авто-состояние — своё у каждого маркетплейса
      if (auto && auto.on && auto.queue && auto.queue[auto.pos]) activeId = auto.queue[auto.pos].id;
    } catch (e) { market = marketFromHost() || "wildberries"; }
    ready = true;
    render();
    await refreshApp();
    setInterval(() => void refreshApp(), 15000);   // авто-переподключение к мосту + досыл буфера
    startScrapePoll();                 // читаем выдачу из DOM (основной способ; перехват fetch — как запасной)
    if (autoIsOn()) runAutoOnPage();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  // искать строку на выбранном маркетплейсе — одна навигация = одно живое действие
  async function searchLine(line) {
    activeId = line.id;
    try { await chrome.storage.local.set({ domeoActive: { id: line.id, name: line.name }, domeoMarket: market }); } catch (e) {}
    const m = MARKETS[market];
    if (m) location.href = m.url(cleanQuery(line.name));
  }

  async function take(p) {
    if (!activeId || !appOk) return;
    await app("sendPrice", {
      spec_item_id: activeId, source: p.source, article_id: p.articleId,
      name: p.name, url: p.url, price: p.price, old_price: p.oldPrice,
      seller: p.seller, brand: p.brand, rating: p.rating, reviews: p.reviews
    });
    priced.add(activeId);
    render();
  }

  // ---------- авто-обход (полуавтомат под присмотром) ----------
  function persistAuto() { if (!auto || !auto.market) return; try { chrome.storage.local.set({ ["domeoAuto_" + auto.market]: auto }); } catch (e) {} }
  function clearAutoTimers() {
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    if (autoInterval) { clearInterval(autoInterval); autoInterval = null; }
    if (autoWaitTimer) { clearTimeout(autoWaitTimer); autoWaitTimer = null; }
  }
  function note(m) {
    autoMsg = m || ""; if (autoMsgT) clearTimeout(autoMsgT);
    if (autoMsg) autoMsgT = setTimeout(() => { autoMsg = ""; render(); }, 9000);
    render();
  }

  // старт/продолжение обхода
  async function startAuto() {
    if (!appOk || !spec.length) return;
    const mk = marketFromHost();                                  // авто идёт по сайту текущей вкладки
    if (!mk || !MARKETS[mk] || !MARKETS[mk].ready) { note("Авто работает на готовых маркетплейсах: Wildberries, DNS, Ситилинк. Открой вкладку одного из них."); return; }
    const sig = spec.length + ":" + (spec[0] && spec[0].id);
    if (auto && auto.market === mk && auto.specSig === sig && !auto.on && auto.pos < auto.queue.length) {
      auto.on = true; auto.batch = 0;                             // продолжаем с паузы
    } else {
      auto = { on: true, market: mk, queue: spec.map((s) => ({ id: s.id, name: s.name })), pos: 0, batch: 0, porcia: 25, paceMin: 20, paceMax: 40, breakMin: 45, breakMax: 90, emptyStreak: 0, specSig: sig };
    }
    persistAuto();
    gotoCurrent();
  }

  // перейти на поиск текущей строки очереди
  function gotoCurrent() {
    if (!auto) return;
    const row = auto.queue[auto.pos];
    if (!row) return void finishAuto();
    activeId = row.id;                                            // только в памяти — восстановится из своего auto на новой странице
    const m = MARKETS[auto.market];
    if (m) location.href = m.url(cleanQuery(row.name));
  }

  // на загруженной странице выдачи: дождаться кандидатов (или антибота/таймаута) и обработать
  function runAutoOnPage() {
    if (autoRan || !autoIsOn()) return;
    autoRan = true;
    if (!appOk) note("Мост недоступен — найденные цены буферизуются, дошлю при переподключении (проход не прерываю).");
    const started = Date.now();
    const WAIT_MS = 12000, GRACE_MS = 4000;
    const poll = () => {
      if (!autoIsOn()) return;
      if (seen.size > 0) return void afterRead();
      if (Date.now() - started > GRACE_MS && looksLikeCaptcha()) return void stopAuto("Антибот/капча на странице — остановился. Пройди проверку руками и жми «Старт».");
      if (Date.now() - started > WAIT_MS) return void afterRead();
      autoWaitTimer = setTimeout(poll, 700);
    };
    autoWaitTimer = setTimeout(poll, 900);
  }

  async function afterRead() {
    if (!autoIsOn()) return;
    const row = auto.queue[auto.pos];
    const items = [...seen.values()].filter((p) => p.price > 0).slice(0, AUTO_K);
    if (items.length) { await pushCandidates(row.id, items); priced.add(row.id); auto.emptyStreak = 0; }
    else { auto.emptyStreak = (auto.emptyStreak || 0) + 1; }
    auto.batch = (auto.batch || 0) + 1;
    auto.pos += 1;
    persistAuto();
    render();
    if (auto.emptyStreak >= 6) return void stopAuto("Шесть пустых выдач подряд — возможно, тихий блок. Остановился, глянь страницу.");
    if (auto.pos >= auto.queue.length) return void finishAuto();
    if (auto.batch >= auto.porcia) { auto.batch = 0; persistAuto(); note("Порция пройдена — передышка, и дальше сам."); scheduleNext(true); return; }
    scheduleNext();
  }

  async function pushCandidates(id, list) {
    for (const p of list) {
      await app("sendPrice", { spec_item_id: id, source: p.source, article_id: p.articleId, name: p.name, url: p.url, price: p.price, old_price: p.oldPrice, seller: p.seller, brand: p.brand, rating: p.rating, reviews: p.reviews });
    }
  }

  // человеческая пауза перед следующей строкой + обратный отсчёт
  function scheduleNext(isBreak) {
    const lo = isBreak ? (auto.breakMin || 45) : (auto.paceMin || 20);
    const hi = isBreak ? (auto.breakMax || 90) : (auto.paceMax || 40);
    const span = Math.max(0, hi - lo);
    autoCountdown = lo + Math.floor(Math.random() * (span + 1));
    render();
    if (autoInterval) clearInterval(autoInterval);
    autoInterval = setInterval(() => { autoCountdown -= 1; if (autoCountdown <= 0) { clearInterval(autoInterval); autoInterval = null; } render(); }, 1000);
    autoTimer = setTimeout(() => { if (autoIsOn()) gotoCurrent(); }, autoCountdown * 1000);
  }

  async function stopAuto(msg) {
    if (auto) auto.on = false;
    clearAutoTimers();
    persistAuto();
    render();
    if (msg) note(msg);
  }

  // начать проход этого маркетплейса заново с первой строки
  async function resetAuto() {
    const mk = marketFromHost();
    clearAutoTimers();
    auto = null;
    if (mk) { try { await chrome.storage.local.remove("domeoAuto_" + mk); } catch (e) {} }
    startAuto();
  }

  async function finishAuto() {
    clearAutoTimers();
    const mk = auto && auto.market;
    auto = null;
    if (mk) { try { await chrome.storage.local.remove("domeoAuto_" + mk); } catch (e) {} }
    note("Авто-обход завершён — спека пройдена" + (MARKETS[mk] ? " (" + MARKETS[mk].name + ")" : "") + ".");
    render();
  }

  // грубая проверка «это страница антибота?» — чтобы не продавливать капчу
  function looksLikeCaptcha() {
    try {
      if (/\/xpvnsulc\/|\/captcha|challenge/i.test(location.pathname + location.search)) return true;
      const t = (document.title || "") + " " + (document.body ? document.body.innerText.slice(0, 1500) : "");
      return /captcha|не\s*робот|подтвердите,?\s*что вы|проверка безопасности|доступ ограничен|qrator|smartcaptcha|too many requests/i.test(t);
    } catch (e) { return false; }
  }

  // ---------- UI (shadow DOM) ----------
  let host, root, box, collapsed = false;
  function ensurePanel() {
    if (host || !document.body) return;
    host = document.createElement("div");
    host.id = "domeo-mp-host";
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647";
    document.body.appendChild(host);
    root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style"); style.textContent = CSS; root.appendChild(style);
    box = document.createElement("div"); box.className = "box"; root.appendChild(box);
  }
  function activeLine() { return spec.find((s) => s.id === activeId) || null; }

  function candCard(p) {
    return '<div class="cand">' +
      '<div class="cn" title="' + esc(p.name) + '">' + esc(p.name) + "</div>" +
      '<div class="cm">' + fmt(p.price) + " ₽" + (p.oldPrice ? ' <s>' + fmt(p.oldPrice) + "</s>" : "") +
        " · " + esc(p.seller || p.brand || p.source) + (p.rating ? " · ★" + p.rating : "") + "</div>" +
      '<div class="ca"><button class="take" data-art="' + esc(p.articleId) + '"' + (appOk ? "" : ' disabled title="приложение не на связи"') + ">взять</button>" +
        '<a class="lnk" href="' + esc(p.url) + '" target="_blank" rel="noopener">↗</a></div>' +
    "</div>";
  }

  function render() {
    ensurePanel(); if (!box) return;
    if (collapsed) {
      box.innerHTML = '<button class="fab">Domeo ' + (appOk ? "●" : "○") + "</button>";
      box.querySelector(".fab").onclick = () => { collapsed = false; render(); };
      return;
    }
    const al = activeLine();
    const marketOpts = Object.keys(MARKETS).map((k) =>
      '<option value="' + k + '"' + (k === market ? " selected" : "") + ">" + esc(MARKETS[k].name) + (MARKETS[k].ready ? "" : " (скоро)") + "</option>").join("");

    // блок активной строки: кандидаты с текущей страницы
    let activeBlock = "";
    if (al) {
      const cands = [...seen.values()].slice(-12).reverse().map(candCard).join("");
      activeBlock = '<div class="active">' +
        '<div class="ahd">Ищем: <b>' + esc(al.name) + '</b><button class="cancel">к списку</button></div>' +
        (cands || '<div class="empty">Жду выдачу… если пусто — пролистни страницу или выбери «готовый» маркетплейс.</div>') +
      "</div>";
    }

    // товары текущей страницы (когда активной строки нет) — для экспорта/обзора
    let pageBlock = "";
    if (!al && seen.size) {
      const items = [...seen.values()].slice(-10).reverse().map(candCard).join("");
      pageBlock = '<div class="active"><div class="ahd">На странице (выбери строку ниже, чтобы «взять»):</div>' + items + "</div>";
    }

    // список строк спеки
    let specBlock;
    if (!appOk) specBlock = '<div class="empty">Приложение Domeo не на связи. Запусти его, открой спеку — строки появятся здесь. Порт — в настройках расширения.</div>';
    else if (spec.length === 0) specBlock = '<div class="empty">В Domeo не открыта спека. Открой/разбери спецификацию.</div>';
    else {
      const doneIds = auto && auto.queue ? new Set(auto.queue.slice(0, auto.pos).map((q) => q.id)) : null;
      const isDone = (id) => priced.has(id) || (doneIds && doneIds.has(id));
      specBlock = spec.map((s) =>
        '<div class="line' + (s.id === activeId ? " on" : "") + '">' +
          '<div class="ln">' + (isDone(s.id) ? "✓ " : "") + esc(s.name) + (s.qty ? ' <span class="q">×' + s.qty + "</span>" : "") + "</div>" +
          '<button class="find" data-id="' + esc(s.id) + '"' + (autoIsOn() ? " disabled" : "") + ">искать</button>" +
        "</div>").join("");
    }

    // полоса авто-обхода (у каждого маркетплейса — свой проход, можно параллельно в разных вкладках)
    const hostM = marketFromHost();
    const canAuto = appOk && spec.length > 0 && !!(hostM && MARKETS[hostM] && MARKETS[hostM].ready);
    const hostName = hostM && MARKETS[hostM] ? MARKETS[hostM].name : "маркетплейс";
    const resume = auto && auto.queue && auto.market === hostM && auto.pos > 0 && auto.pos < auto.queue.length && !auto.on;
    let autoBar;
    if (autoIsOn()) {
      const row = auto.queue[auto.pos];
      autoBar = '<div class="auto on"><button class="astop">⏸ Стоп</button><span class="ast">Авто · ' + esc(MARKETS[auto.market] ? MARKETS[auto.market].name : auto.market) + " " + (auto.pos + 1) + "/" + auto.queue.length +
        " · порция " + auto.batch + "/" + auto.porcia +
        (autoCountdown > 0 ? " · дальше " + autoCountdown + " c" : (row ? " · ищу «" + esc(cleanQuery(row.name)) + "»" : "")) + "</span></div>";
    } else {
      autoBar = '<div class="auto"><button class="astart"' + (canAuto ? "" : " disabled") +
        ' title="' + (canAuto ? "Пройдёт по строкам сам, порциями; у каждого маркетплейса свой проход — WB, DNS и Ситилинк можно открыть в разных вкладках параллельно" : "Открой вкладку готового маркетплейса (Wildberries, DNS, Ситилинк), подними приложение и открой спеку") + '">▶ ' +
        (resume ? "Старт " + esc(hostName) + " (с " + (auto.pos + 1) + ")" : "Старт авто · " + esc(hostName)) + "</button>" +
        (resume ? '<button class="areset" title="Начать проход заново с первой строки">↺</button>' : "") +
        '<span class="ast">' + (canAuto ? "свой проход по " + esc(hostName) + ", параллельно с другими вкладками" : "авто недоступно здесь") + "</span></div>";
    }
    const msgBar = autoMsg ? '<div class="amsg">' + esc(autoMsg) + "</div>" : "";

    box.innerHTML =
      '<div class="hd"><b>Domeo</b><span class="dot ' + (appOk ? "on" : "off") + '"></span>' +
        '<span class="st">' + (appOk ? "спека: " + spec.length : "нет приложения") + "</span>" +
        (pending > 0 ? '<span class="pend" title="Цены в буфере — дошлю при переподключении к мосту">⏳ ' + pending + "</span>" : "") +
        '<span class="sp"></span>' +
        '<button class="exp" title="Скачать найденное в файл">⤓</button>' +
        '<button class="rf" title="Обновить из приложения">⟳</button>' +
        '<button class="cl">—</button></div>' +
      '<div class="ctl">Маркетплейс: <select class="mk">' + marketOpts + "</select></div>" +
      autoBar + msgBar +
      activeBlock + pageBlock +
      '<div class="bd">' + specBlock + "</div>";

    box.querySelector(".cl").onclick = () => { collapsed = true; render(); };
    box.querySelector(".rf").onclick = refreshApp;
    box.querySelector(".exp").onclick = exportFile;
    box.querySelector(".mk").onchange = (ev) => { market = ev.target.value; try { chrome.storage.local.set({ domeoMarket: market }); } catch (e) {} render(); };
    box.querySelectorAll(".find").forEach((b) => b.onclick = () => {
      const line = spec.find((s) => s.id === b.getAttribute("data-id"));
      if (line) void searchLine(line);
    });
    const cancel = box.querySelector(".cancel");
    if (cancel) cancel.onclick = () => { activeId = ""; try { chrome.storage.local.remove("domeoActive"); } catch (e) {} render(); };
    box.querySelectorAll(".take").forEach((b) => b.onclick = () => {
      const p = seen.get(b.getAttribute("data-art"));
      if (p) void take(p);
    });
    const asb = box.querySelector(".astart"); if (asb) asb.onclick = () => void startAuto();
    const apb = box.querySelector(".astop"); if (apb) apb.onclick = () => void stopAuto(null);
    const arb = box.querySelector(".areset"); if (arb) arb.onclick = () => void resetAuto();
  }

  function exportFile() {
    const blob = new Blob([JSON.stringify([...seen.values()], null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "domeo-prices.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  function fmt(n) { return Number(n).toLocaleString("ru-RU"); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  const CSS =
    ".box{font:13px/1.4 system-ui,Segoe UI,Arial;width:360px;max-height:72vh;display:flex;flex-direction:column;background:#fff;color:#1a1a1a;border:1px solid #d9d9d9;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.18);overflow:hidden}" +
    ".fab{font:600 13px system-ui;padding:8px 12px;border:0;border-radius:20px;background:#5b2be0;color:#fff;cursor:pointer;box-shadow:0 6px 18px rgba(0,0,0,.2)}" +
    ".hd{display:flex;align-items:center;gap:6px;padding:8px 10px;background:#f6f4fe;border-bottom:1px solid #eee}" +
    ".hd .sp{flex:1}.hd b{font-size:13px}" +
    ".hd button{font:12px system-ui;border:1px solid #ddd;background:#fff;border-radius:6px;padding:2px 7px;cursor:pointer}" +
    ".dot{width:8px;height:8px;border-radius:50%}.dot.on{background:#2ea043}.dot.off{background:#c0392b}" +
    ".st{color:#666;font-size:12px}" +
    ".pend{color:#b26a00;font-size:12px;margin-left:6px;white-space:nowrap}" +
    ".ctl{padding:7px 10px;border-bottom:1px solid #f0f0f0;color:#555;font-size:12px}" +
    ".ctl select{font:12px system-ui;padding:3px;max-width:210px}" +
    ".auto{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid #f0f0f0}" +
    ".auto.on{background:#eef7ee}" +
    ".astart{font:600 12px system-ui;border:1px solid #2ea043;background:#2ea043;color:#fff;border-radius:6px;padding:4px 12px;cursor:pointer;white-space:nowrap}" +
    ".astart[disabled]{background:#bbb;border-color:#bbb;cursor:default}" +
    ".astop{font:600 12px system-ui;border:1px solid #c0392b;background:#fff;color:#c0392b;border-radius:6px;padding:4px 12px;cursor:pointer;white-space:nowrap}" +
    ".areset{font:12px system-ui;border:1px solid #bbb;background:#fff;color:#666;border-radius:6px;padding:4px 8px;cursor:pointer;margin-left:4px}" +
    ".ast{color:#555;font-size:12px;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    ".amsg{background:#fff7e6;color:#7a5900;border-bottom:1px solid #ffe3a3;padding:6px 10px;font-size:12px}" +
    ".bd{overflow:auto;padding:4px 6px}" +
    ".empty{color:#888;padding:12px 8px;text-align:center}" +
    ".line{display:flex;align-items:center;gap:6px;padding:5px 6px;border-bottom:1px solid #f3f3f3}" +
    ".line.on{background:#f6f4fe}" +
    ".line .ln{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    ".line .q{color:#999}" +
    ".find{font:12px system-ui;border:1px solid #5b2be0;background:#fff;color:#5b2be0;border-radius:6px;padding:3px 10px;cursor:pointer;white-space:nowrap}" +
    ".line.on .find{background:#5b2be0;color:#fff}" +
    ".active{background:#fcfbff;border-bottom:2px solid #eee;padding:4px 6px 6px;max-height:40vh;overflow:auto}" +
    ".ahd{font-size:12px;color:#444;margin:4px 2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    ".ahd .cancel{float:right;font:11px system-ui;border:1px solid #ddd;background:#fff;border-radius:5px;padding:1px 6px;cursor:pointer}" +
    ".cand{padding:5px 4px;border-top:1px solid #f0f0f0}" +
    ".cn{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    ".cm{color:#555;font-size:12px;margin:2px 0 4px}.cm s{color:#aaa}" +
    ".ca{display:flex;gap:6px;align-items:center}" +
    ".take{font:12px system-ui;border:1px solid #2ea043;background:#2ea043;color:#fff;border-radius:6px;padding:3px 12px;cursor:pointer}" +
    ".take[disabled]{background:#bbb;border-color:#bbb;cursor:default}" +
    ".lnk{text-decoration:none;color:#5b2be0;font-size:15px;padding:0 3px}";
})();
