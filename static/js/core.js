const $ = (s) => document.querySelector(s);
const statusEl = $("#status"), statusText = $("#statusText");
let statusTimer, autoTimer = null, current = { ticker: "BBCA", interval: "1d" };
let quoteTicker = null;
function showStatus(msg, sticky=false){ statusText.textContent = msg; statusEl.style.display="flex";
  clearTimeout(statusTimer); if(!sticky) statusTimer = setTimeout(()=>statusEl.style.display="none", 1400); }
const fmt = (n,d=0) => (n===null||n===undefined||isNaN(n)) ? "-" : Number(n).toLocaleString("id-ID",{minimumFractionDigits:d,maximumFractionDigits:d});
const idr = (n) => "Rp " + fmt(n);
function signalClass(s){ if(s.includes("STRONG"))return "STRONG"; if(s==="BUY")return "BUY"; if(s==="ACCUMULATE")return "ACC"; if(s==="HOLD")return "HOLD"; if(s==="SELL")return "SELL"; return "AVOID"; }
function scoreColor(s){ return s>=80 ? "#16a34a" : s>=65 ? "#4b8f6a" : s>=40 ? "#8a948d" : "#e5484d"; }
function chg(v){ return `<span class="chg" style="color:${v>=0?'#26a69a':'#ef5350'}">${v>=0?'+':'−'}${fmt(Math.abs(v),2)}%</span>`; }

async function mapLimit(items, limit, fn){
  const ret = new Array(items.length);
  let i = 0;
  const n = Math.max(1, Math.min(limit, items.length));
  const worker = async () => { while(i < items.length){ const idx = i++; ret[idx] = await fn(items[idx], idx); } };
  await Promise.all(Array.from({length:n}, () => worker().catch(()=>{})));
  return ret;
}
function throttle(fn, ms){ let t = 0; return function(){ const now = Date.now(); if(now - t >= ms){ t = now; fn(); } }; }

async function fetchJSON(url, opts){
  opts = opts || {};
  const retries = (opts.retries!=null) ? opts.retries : 2;
  let delay = 2500, lastErr = null;
  for(let i=0;i<=retries;i++){
    try{
      const r = await fetch(url, opts.fetchOpts);
      if(r.ok){
        try{ return await r.json(); }
        catch(e){ throw new Error("Format respons tidak dikenali"); }
      }
      if([502,503,504,429].indexOf(r.status)>=0 && i<retries){
        await new Promise(s=>setTimeout(s,delay)); delay=Math.round(delay*1.5); continue;
      }
      let msg = "HTTP "+r.status;
      try{ const j = await r.json(); if(j && j.error) msg = j.error; }catch(e){}
      throw new Error(msg);
    }catch(err){
      lastErr = err;
      if(i<retries){ await new Promise(s=>setTimeout(s,delay)); delay=Math.round(delay*1.5); continue; }
      throw lastErr;
    }
  }
}

/* ---------- Live chart: TradingView Lightweight Charts (free, open-source) ---------- */
const charts = { analysis: null, live: null };
let showBench = false;
const TV_INT = { D: "1d", "60": "1h", "15": "15m", "5": "5m", W: "1wk" };
const LIBSRC = [
  "/static/vendor/lightweight-charts.standalone.production.js",
  "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js",
];

const ChartKit = (function () {
  let ready = false;
  const queue = [];
  function load(cb) {
    if (ready || window.LightweightCharts) { ready = true; cb(); return; }
    queue.push(cb);
    if (document.getElementById("lwlib")) return;
    let i = 0;
    const tryNext = () => {
      if (i >= LIBSRC.length) { queue.splice(0).forEach((f) => f(new Error("lib"))); return; }
      const s = document.createElement("script");
      s.id = "lwlib"; s.async = true; s.src = LIBSRC[i++];
      s.onload = () => { ready = true; queue.splice(0).forEach((f) => f()); };
      s.onerror = () => { s.remove(); tryNext(); };
      document.head.appendChild(s);
    };
    tryNext();
  }

  function baseOptions(el, intraday) {
    const dark = document.documentElement.dataset.theme === "dark";
    const txt = dark ? "#8aa093" : "#5f6f66";
    const grid = dark ? "rgba(255,255,255,0.06)" : "rgba(15,23,18,0.06)";
    const line = dark ? "rgba(255,255,255,0.12)" : "rgba(15,23,18,0.12)";
    const cross = dark ? "rgba(255,255,255,.35)" : "rgba(15,23,18,.35)";
    return {
      width: Math.max(el.clientWidth || 0, 320),
      height: el.clientHeight || 460,
      layout: { background: { type: "solid", color: "transparent" }, textColor: txt,
        fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: 10 },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: line, scaleMargins: { top: 0.08, bottom: 0.05 } },
      timeScale: { borderColor: line, timeVisible: !!intraday, secondsVisible: false, rightOffset: 6, barSpacing: 7 },
      crosshair: { mode: 1, vertLine: { color: cross, labelBackgroundColor: "#16a34a" },
        horzLine: { color: cross, labelBackgroundColor: "#16a34a" } },
    };
  }

  function lineSeries(chart, color, width, dashed) {
    return chart.addLineSeries({ color: color, lineWidth: width || 1, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: false, lineStyle: dashed ? 2 : 0 });
  }

  function mount(wrap, p) {
    const LWC = window.LightweightCharts;
    const intraday = !["1d", "1wk", "1mo", "3mo"].includes(p.interval);
    wrap.innerHTML = '<div class="lw-main"></div><div class="lw-rsi"><div class="lw-rsi-label">RSI 14</div></div>';
    const mainEl = wrap.querySelector(".lw-main");
    const rsiEl = wrap.querySelector(".lw-rsi");

    const chart = LWC.createChart(mainEl, baseOptions(mainEl, intraday));
    const rsiOpts = baseOptions(rsiEl, intraday);
    rsiOpts.rightPriceScale = { borderColor: "rgba(255,255,255,0.12)", scaleMargins: { top: 0.15, bottom: 0.15 } };
    const rsiChart = LWC.createChart(rsiEl, rsiOpts);

    const candle = chart.addCandlestickSeries({ upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
      wickUpColor: "#26a69a", wickDownColor: "#ef5350", priceLineVisible: false, lastValueVisible: true });
    const vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol",
      priceLineVisible: false, lastValueVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });

    const series = {
      ma20: lineSeries(chart, "#f39c12", 1),
      ma50: lineSeries(chart, "#42a5f5", 1),
      ma200: lineSeries(chart, "#ab47bc", 2),
      ema21: lineSeries(chart, "#26c6da", 1, true),
      avwap: lineSeries(chart, "#0f766e", 1, true),
      bench: lineSeries(chart, "#94a3b8", 1, true),
      supertrend_up: lineSeries(chart, "#26a69a", 2),
      supertrend_down: lineSeries(chart, "#ef5350", 2),
    };

    const rsi = rsiChart.addLineSeries({ color: "#ab47bc", lineWidth: 1, priceLineVisible: false,
      lastValueVisible: true, autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
    rsi.createPriceLine({ price: 70, color: "rgba(239,83,80,.45)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
    rsi.createPriceLine({ price: 30, color: "rgba(38,166,154,.45)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
    rsi.createPriceLine({ price: 50, color: "rgba(255,255,255,.15)", lineWidth: 1, lineStyle: 3, axisLabelVisible: false, title: "" });

    const api = { wrap, chart, rsiChart, candle, vol, series, rsi, priceLines: [], liveLine: null,
      last: null, ticker: p.ticker, interval: p.interval, ro: null };

    const sync = (src, dst) => src.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) dst.timeScale().setVisibleLogicalRange(r); });
    sync(chart, rsiChart); sync(rsiChart, chart);

    applyData(api, p);

    if (window.ResizeObserver) {
      api.ro = new ResizeObserver(() => resize(api));
      api.ro.observe(wrap);
    }
    return api;
  }

  function applyData(api, p) {
    api.candle.setData(p.candles || []);
    api.vol.setData(p.volume || []);
    Object.keys(api.series).forEach((k) => {
      if (k !== "bench") api.series[k].setData((p.overlays && p.overlays[k]) || []);
    });
    api.benchmark = p.benchmark || [];
    api.series.bench.setData(showBench ? api.benchmark : []);
    api.priceLines.forEach((pl) => api.candle.removePriceLine(pl));
    api.priceLines = [];
    (p.levels || []).forEach((lv) => api.priceLines.push(api.candle.createPriceLine({
      price: lv.price, color: lv.color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: lv.title })));
    api.rsi.setData(p.rsi || []);
    api.last = (p.candles && p.candles.length) ? Object.assign({}, p.candles[p.candles.length - 1]) : null;
    api.ticker = p.ticker;
    api.interval = p.interval;
    api.chart.timeScale().fitContent();
    resize(api);
  }

  function updateLast(api, price, hi, lo) {
    if (!api || !api.last || price == null) return;
    const c = Object.assign({}, api.last);
    c.close = price;
    if (hi != null) c.high = Math.max(c.high, hi);
    if (lo != null) c.low = Math.min(c.low, lo);
    api.candle.update(c);
    api.last = c;
    if (api.liveLine) { api.candle.removePriceLine(api.liveLine); api.liveLine = null; }
    api.liveLine = api.candle.createPriceLine({ price: price, color: "#16a34a", lineWidth: 1,
      lineStyle: 1, axisLabelVisible: true, title: "LIVE" });
  }

  function resize(api) {
    const w = api.wrap.clientWidth;
    if (!w) return;
    try { api.chart.applyOptions({ width: w }); api.rsiChart.applyOptions({ width: w }); } catch (e) {}
  }

  function destroy(api) {
    if (!api) return;
    try { if (api.ro) api.ro.disconnect(); } catch (e) {}
    try { api.chart.remove(); } catch (e) {}
    try { api.rsiChart.remove(); } catch (e) {}
  }

  function equity(wrap, dates, values) {
    const LWC = window.LightweightCharts;
    wrap.innerHTML = '<div class="lw-main" style="height:280px"></div>';
    const el = wrap.querySelector(".lw-main");
    const chart = LWC.createChart(el, baseOptions(el, false));
    const area = chart.addAreaSeries({ lineColor: "#26a69a", topColor: "rgba(38,166,154,0.35)",
      bottomColor: "rgba(38,166,154,0.0)", lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
    const data = [];
    for (let i = 0; i < dates.length && i < values.length; i++) {
      if (dates[i] && values[i] != null) data.push({ time: dates[i], value: values[i] });
    }
    area.setData(data);
    chart.timeScale().fitContent();
    const api = { wrap, chart, ro: null };
    if (window.ResizeObserver) {
      api.ro = new ResizeObserver(() => { const w = wrap.clientWidth; if (w) chart.applyOptions({ width: w }); });
      api.ro.observe(wrap);
    }
    return api;
  }

  return { load: load, mount: mount, updateLast: updateLast, resize: resize, destroy: destroy, equity: equity };
})();

async function loadChart(name, selector, ticker, interval, refresh) {
  const wrap = document.querySelector(selector);
  if (!wrap) return;
  if (charts[name]) { ChartKit.destroy(charts[name]); charts[name] = null; }
  wrap.innerHTML = '<div class="empty" style="padding:40px">Memuat chart live...</div>';
  ChartKit.load(async (err) => {
    if (err) { wrap.innerHTML = '<div class="empty">Gagal memuat library chart (butuh internet).</div>'; return; }
    try {
      const p = await fetchJSON(`/api/ohlc?ticker=${encodeURIComponent(ticker)}&interval=${interval}&refresh=${refresh ? 1 : 0}`);
      if (p.error) throw new Error(p.error);
      if (!p.candles || !p.candles.length) throw new Error("data chart kosong");
      charts[name] = ChartKit.mount(wrap, p);
    } catch (e) {
      wrap.innerHTML = `<div class="empty">Gagal: ${e.message}</div>`;
    }
  });
}

