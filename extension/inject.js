// inject.js — выполняется В КОНТЕКСТЕ страницы (MAIN world), внедряется из content.js как можно
// раньше. Перехватывает ОТВЕТЫ fetch/XHR маркетплейса, которые страница и так грузит, когда ВЫ
// смотрите товары, и шлёт разобранные позиции в content.js. Своих запросов к сайту НЕ делает.
//
// Добавить маркетплейс = написать парсер parseX(data,url) + одна строка в ADAPTERS + хост в
// manifest.json (matches и web_accessible_resources). Остальное общее.
(function () {
  "use strict";
  if (window.__domeoInjected) return;   // уже внедрён (MAIN-контент-скрипт + запасной <script>) — не патчим fetch дважды
  window.__domeoInjected = true;
  const TAG = "domeo-mp";
  // DEBUG-режим: для сайтов без готового парсера пишем образец ответа в консоль страницы
  // ([domeo-capture]), чтобы по нему дописать парсер. Выключить в релизе: false.
  const DEBUG_CAPTURE = true;
  function dbg() { if (!DEBUG_CAPTURE) return; try { console.log.apply(console, ["[domeo]"].concat([].slice.call(arguments))); } catch (e) {} }

  function num(s) {
    if (s == null) return null;
    const n = String(s).replace(/[^\d]/g, "");
    return n ? parseInt(n, 10) : null;
  }

  // ======================= парсеры по сайтам =======================

  // --- Wildberries (готово, проверено на живом ответе) ---
  function parseWb(data) {
    const products = (data && data.products) || (data && data.data && data.data.products) || null;
    if (!Array.isArray(products)) return null;
    const out = [];
    for (const p of products) {
      const size = Array.isArray(p.sizes) ? (p.sizes.find((s) => s && s.price) || p.sizes[0]) : null;
      const kop = (size && size.price && (size.price.product ?? size.price.total ?? size.price.basic)) ?? p.salePriceU ?? p.priceU ?? null;
      if (!kop || !p.id) continue;
      out.push({
        source: "wildberries", articleId: String(p.id), name: p.name || "",
        brand: p.brand || "", seller: p.supplier || "",
        price: Math.round(kop / 100),
        oldPrice: size && size.price && size.price.basic ? Math.round(size.price.basic / 100) : null,
        rating: p.reviewRating ?? p.rating ?? null, reviews: p.feedbacks ?? null,
        url: "https://www.wildberries.ru/catalog/" + p.id + "/detail.aspx"
      });
    }
    return out.length ? out : null;
  }

  // --- Ozon (ЧЕРНОВИК: уточнить пути title/price/link на живом ответе composer-api) ---
  function parseOzon(data) {
    const states = data && data.widgetStates;
    if (!states || typeof states !== "object") return null;
    const out = [];
    for (const key of Object.keys(states)) {
      if (!/search|tile|product/i.test(key)) continue;
      let w; try { w = JSON.parse(states[key]); } catch (e) { continue; }
      const items = w.items || w.products || [];
      for (const it of items) {
        const name = it.title || (it.mainState && it.mainState.title) || "";
        const price = num(it.price || (it.mainState && it.mainState.price));
        if (!name || !price) continue;
        const link = (it.action && it.action.link) || it.link || "";
        out.push({
          source: "ozon", articleId: String(it.sku || it.productId || it.id || ""),
          name: String(name), brand: it.brand || "", seller: it.seller || "", price: price,
          oldPrice: num(it.originalPrice) || null, rating: it.rating || null, reviews: it.reviewCount || null,
          url: link ? (String(link).startsWith("http") ? link : "https://www.ozon.ru" + link) : ""
        });
      }
    }
    return out.length ? out : null;
  }

  // --- ЗАГЛУШКИ: заполняются по живому ответу каждого сайта ---
  function parseYaMarket(data, url) { return null; }     // TODO market.yandex.ru
  function parseMegamarket(data, url) { return null; }   // TODO megamarket.ru
  function parseVseinst(data, url) { return null; }      // TODO vseinstrumenti.ru
  function parseLemana(data, url) { return null; }       // TODO lemanapro.ru (Леруа/Лемана ПРО)
  // DNS: ответ /ajax-state/product-buy/ → { data:{ states:[ { data:{ id, name, price:{current,previous} } } ] } }
  // Цена уже в рублях (не копейки). URL карточки по id не строится — даём поиск по имени.
  function parseDns(data) {
    if (!data || !data.data || !Array.isArray(data.data.states)) return null;
    const out = [];
    for (const st of data.data.states) {
      const d = st && st.data;
      if (!d || !d.price || !d.name) continue;
      const price = d.price.current;
      if (!price) continue;
      out.push({
        source: "dns", articleId: String(d.id || ""), name: d.name, brand: "", seller: "DNS",
        price: Math.round(price), oldPrice: d.price.previous ? Math.round(d.price.previous) : null,
        rating: null, reviews: null,
        url: "https://www.dns-shop.ru/search/?q=" + encodeURIComponent(d.name)
      });
    }
    return out.length ? out : null;
  }
  // Ситилинк: GraphQL → data.productsFilter.record.products[] c price.current (строка, рубли), brand, slug.
  function parseCitilink(data) {
    const products = data && data.data && data.data.productsFilter &&
      data.data.productsFilter.record && data.data.productsFilter.record.products;
    if (!Array.isArray(products)) return null;
    const out = [];
    for (const p of products) {
      const price = p.price && p.price.current ? num(p.price.current) : null;
      if (!price || !p.name) continue;
      out.push({
        source: "citilink", articleId: String(p.id || ""), name: p.name,
        brand: (p.brand && p.brand.name) || "", seller: "Ситилинк",
        price: price, oldPrice: p.price && p.price.old ? (num(p.price.old) || null) : null,
        rating: p.rating ? parseFloat(p.rating) : null,
        reviews: p.counters ? (p.counters.opinions || p.counters.reviews || null) : null,
        url: p.slug ? "https://www.citilink.ru/product/" + p.slug + "/" : ""
      });
    }
    return out.length ? out : null;
  }
  function parsePetrovich(data, url) { return null; }    // TODO petrovich.ru

  // ======================= реестр адаптеров =======================
  const ADAPTERS = [
    { id: "wildberries",    host: /wildberries\.ru|wb\.ru/i,        want: /search|catalog|cards|detail/i,     parse: parseWb },
    { id: "ozon",           host: /ozon\.ru/i,                      want: /composer-api|entrypoint|search/i,  parse: parseOzon },
    { id: "yandexmarket",   host: /market\.yandex\.ru/i,            want: /api|search|resolve|cataloger/i,    parse: parseYaMarket },
    { id: "megamarket",     host: /megamarket\.ru/i,                want: /api|search|catalog/i,              parse: parseMegamarket },
    { id: "vseinstrumenti", host: /vseinstrumenti\.ru/i,            want: /api|search|catalog|graphql/i,      parse: parseVseinst },
    { id: "lemana",         host: /lemanapro\.ru|leroymerlin\.ru/i, want: /api|search|catalog|graphql/i,      parse: parseLemana },
    { id: "dns",            host: /dns-shop\.ru/i,                  want: /product-buy/i,                     parse: parseDns },
    { id: "citilink",       host: /citilink\.ru/i,                  want: /api|search|catalog|graphql/i,      parse: parseCitilink },
    { id: "petrovich",      host: /petrovich\.ru/i,                 want: /api|search|catalog/i,              parse: parsePetrovich }
  ];

  function adapterFor(url) { return ADAPTERS.find((a) => a.host.test(url)); }
  function interesting(url) { const a = adapterFor(url); return !!(a && a.want.test(url)); }

  // образец ответа в консоль — чтобы дописать парсер по живым данным твоего браузинга
  const _capCount = {};
  function captureSample(a, url, data) {
    if (!DEBUG_CAPTURE) return;
    _capCount[a.id] = (_capCount[a.id] || 0) + 1;
    if (_capCount[a.id] > 5) return; // не больше 5 образцов на сайт за сессию
    try {
      const top = data && typeof data === "object" ? Object.keys(data).slice(0, 30) : String(typeof data);
      console.log("[domeo-capture] " + a.id + " #" + _capCount[a.id] + "  " + String(url).slice(0, 150) +
        "\n  keys=" + JSON.stringify(top) +
        "\n  sample=" + JSON.stringify(data).slice(0, 1500));
    } catch (e) {}
  }

  function handle(url, text) {
    if (!text) return;
    let data; try { data = JSON.parse(text); } catch (e) { return; }
    const a = adapterFor(url);
    if (!a || !a.want.test(url)) return;
    let items; try { items = a.parse(data, url); } catch (e) { items = null; }
    dbg(a.id, items && items.length ? items.length + " поз." : "0 (парсер вернул пусто)", String(url).slice(0, 110));
    if (items && items.length) window.postMessage({ [TAG]: true, source: a.id, url: url, items: items }, "*");
    else captureSample(a, url, data); // парсер-заглушка → снимаем образец для доводки
  }

  // ======================= перехват fetch / XHR =======================
  const _fetch = window.fetch;
  if (_fetch) {
    window.fetch = function () {
      const args = arguments;
      return _fetch.apply(this, args).then((res) => {
        try {
          const a0 = args[0];
          const url = (a0 && a0.url) || String(a0 || "");
          if (interesting(url)) { dbg("fetch видит", String(url).slice(0, 110)); res.clone().text().then((t) => handle(url, t)).catch(() => {}); }
        } catch (e) {}
        return res;
      });
    };
  }

  const _open = XMLHttpRequest.prototype.open;
  const _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) { this.__domeoUrl = url; return _open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function () {
    try {
      const url = this.__domeoUrl || "";
      if (interesting(url)) { dbg("xhr видит", String(url).slice(0, 110)); this.addEventListener("load", function () { try { handle(url, this.responseText); } catch (e) {} }); }
    } catch (e) {}
    return _send.apply(this, arguments);
  };
  dbg("перехват активен (MAIN) — жду запросы выдачи");
})();
