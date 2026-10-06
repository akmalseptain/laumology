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

document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  const name = t.dataset.tab;
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active", x.dataset.tab===name));
  document.querySelectorAll(".panel").forEach(x=>x.classList.remove("active"));
  const panel = $("#panel-"+name); if(panel) panel.classList.add("active");
  if(name==="live") loadLiveChart();
  if(name==="portofolio") refreshPortfolio();
  if(name==="analisis" && charts.analysis) setTimeout(()=>ChartKit.resize(charts.analysis), 80);
  if(window.matchMedia("(max-width:900px)").matches) window.scrollTo({top:0, behavior:"smooth"});
});
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{ $("#ticker").value=c.dataset.t; document.querySelectorAll(".chip").forEach(x=>x.classList.remove("active")); c.classList.add("active"); analyze(); });
$("#goBtn").onclick = () => analyze();
$("#ticker").addEventListener("keydown", e => { if(e.key==="Enter") analyze(); });
$("#interval").onchange = () => analyze();
$("#auto").onchange = (e) => {
  clearInterval(autoTimer);
  if(e.target.checked) autoTimer = setInterval(()=>analyze(true), 60000);
};

async function analyze(silent=false){
  const ticker = ($("#ticker").value||"").trim().toUpperCase();
  if(!ticker) return;
  const interval = $("#interval").value;
  current = { ticker, interval };
  if(!silent) showStatus("Mengambil " + ticker + " (" + interval + ")...", true);
  $("#goBtn").disabled = true;
  try{
    const d = await fetchJSON(`/api/analyze?ticker=${encodeURIComponent(ticker)}&interval=${interval}&refresh=${$("#refresh").checked?1:0}&log=${silent?0:1}`, {retries:2});
    if(d.error) throw new Error(d.error);
    render(d);
    if(!silent) showStatus("Selesai");
  }catch(e){ if(!silent){ $("#result").innerHTML = `<div class="card glass modish empty">Gagal: ${e.message}</div>`; showStatus("Gagal"); } }
  finally{ $("#goBtn").disabled=false; }
}

function render(d){
  const sc = signalClass(d.signal), cc = scoreColor(d.score);
  const comps = Object.entries(d.components).map(([k,v])=>{
    const max = {"tren":20,"momentum":20,"kekuatan":15,"volume":15,"setup":15,"risiko":15,"konfluensi":15}[k]||20;
    return `<div class="comp"><span class="name">${k}</span><span class="bar"><i style="width:${Math.min(100,v/max*100)}%"></i></span><span class="num">${fmt(v,0)}</span></div>`;
  }).join("");
  const checks = (d.checklist||[]).map(c=>`<div class="check ${c.pass?'ok':'no'}"><span class="ic">${c.pass?'✓':'✗'}</span>${c.label}</div>`).join("");
  const reasons = d.reasons.length? d.reasons.map(x=>`<li>${x}</li>`).join("") : "<li style='color:#737373;border-left-color:rgba(255,255,255,.15)'>Tidak ada faktor bullish kuat.</li>";
  const warns = d.warnings.length? d.warnings.map(x=>`<li>${x}</li>`).join("") : "<li style='color:#737373;border-left-color:rgba(255,255,255,.15)'>Tidak ada peringatan.</li>";
  const rsTxt = d.rs_change===null ? "n/a" : (d.rs_change>=0?"+":"−")+fmt(Math.abs(d.rs_change),1)+"%";
  const rsCls = d.rs_strong ? "v-up" : "v-red";
  const stCls = d.st_dir_up ? "v-up" : "v-red";
  const passed = (d.checklist||[]).filter(c=>c.pass).length;

  $("#result").innerHTML = `
    <div class="card glass modish hero">
      <div class="ring" style="background:conic-gradient(${cc} ${d.score*3.6}deg, rgba(255,255,255,.06) 0)">
        <div class="val"><b style="color:${cc}">${d.score}</b><span>/100</span></div>
      </div>
      <div class="headline">
        <span class="badge-lg s-${sc}">${d.signal}</span>
        <span class="badge-lg s-HOLD" style="margin-left:6px">${d.action}</span>
        <h1 class="glow-text">${d.ticker}</h1>
        <div class="price"><span id="livePrice">${idr(d.price)}</span> <span id="liveChg">${chg(d.change_1d)}</span>
          <span id="liveDot" class="live-dot" style="display:${d.live?'inline-block':'none'};vertical-align:middle;margin-left:8px"></span></div>
        <div class="meta">${d.trend} &middot; W:${d.weekly_trend} &middot; ${d.regime} &middot; ${d.last_date} &middot; ${d.bars} bar
          <span id="liveStamp" class="mono" style="color:#525252">${d.live?("· LIVE "+(d.quote_source||"")):""}</span></div>
      </div>
      <div style="text-align:center;min-width:150px">
        <div class="mono" style="font-size:9px;color:#525252;letter-spacing:.16em">CONFIDENCE</div>
        <div class="grade" style="color:${cc};margin-top:2px">${d.grade}</div>
        <div class="mono" style="font-size:20px;font-weight:900;margin-top:2px">${d.confidence}%</div>
        <div class="mono" style="font-size:9px;color:#525252;margin-top:4px">${passed}/${d.checklist.length} faktor</div>
      </div>
    </div>

    <div class="card glass modish">
      <div class="sec"><span class="num">01</span><div class="line"></div><span class="badge">Trade Plan</span></div>
      <div class="grid">
        <div class="metric hl"><div class="k">Beli Sekarang</div><div class="v v-white">${idr(d.entry)}</div></div>
        <div class="metric hl"><div class="k">Zona Beli</div><div class="v v-muted">${fmt(d.buy_zone_low)} – ${fmt(d.buy_zone_high)}</div></div>
        <div class="metric"><div class="k">Beli Breakout</div><div class="v v-up">${idr(d.entry_breakout)}</div></div>
        <div class="metric"><div class="k">Stop Loss</div><div class="v v-red">${idr(d.stop_loss)}</div></div>
        <div class="metric"><div class="k">Trailing Stop</div><div class="v v-red">${idr(d.stop_trail)}</div></div>
        <div class="metric"><div class="k">Risiko / Trade</div><div class="v v-muted">${fmt(d.risk_pct,2)}%</div></div>
        <div class="metric"><div class="k">TP1 (RR 1:${fmt(d.rr1,1)})</div><div class="v v-up">${idr(d.tp1)}</div></div>
        <div class="metric"><div class="k">TP2 (RR 1:${fmt(d.rr2,1)})</div><div class="v v-up">${idr(d.tp2)}</div></div>
        <div class="metric"><div class="k">TP3 (RR 1:${fmt(d.rr3,1)})</div><div class="v v-up">${idr(d.tp3)}</div></div>
      </div>
    </div>

    <div class="card glass modish">
      <div class="sec"><span class="num">02</span><div class="line"></div><span class="badge">Position Sizing</span></div>
      <div class="grid">
        <div class="metric"><div class="k">Saran Lot</div><div class="v v-white">${fmt(d.lots)}</div></div>
        <div class="metric"><div class="k">Nilai Posisi</div><div class="v v-muted">${idr(Math.round(d.position_value))}</div></div>
        <div class="metric"><div class="k">Modal</div><div class="v v-muted">${idr(100000000)}</div></div>
        <div class="metric"><div class="k">Risiko (1.5%)</div><div class="v v-red">${idr(Math.round(d.risk_amount))}</div></div>
        <div class="metric"><div class="k">Maks Loss</div><div class="v v-red">${idr(Math.round(d.max_loss))}</div></div>
      </div>
    </div>

    <div class="card glass modish">
      <div class="sec"><span class="num">03</span><div class="line"></div><span class="badge">Indicators</span></div>
      <div class="grid">
        <div class="metric"><div class="k">RSI (14)</div><div class="v v-muted">${fmt(d.rsi,1)}</div></div>
        <div class="metric"><div class="k">ADX</div><div class="v v-muted">${fmt(d.adx,1)}</div></div>
        <div class="metric"><div class="k">+DI / -DI</div><div class="v v-muted">${fmt(d.plus_di,0)}/${fmt(d.minus_di,0)}</div></div>
        <div class="metric"><div class="k">SuperTrend</div><div class="v ${stCls}">${d.st_dir_up?'UP':'DOWN'}</div></div>
        <div class="metric"><div class="k">MACD Hist</div><div class="v v-muted">${fmt(d.macd_hist,2)}</div></div>
        <div class="metric"><div class="k">Stoch %K</div><div class="v v-muted">${fmt(d.stoch_k,1)}</div></div>
        <div class="metric"><div class="k">CCI</div><div class="v v-muted">${fmt(d.cci,0)}</div></div>
        <div class="metric"><div class="k">MFI</div><div class="v v-muted">${fmt(d.mfi,1)}</div></div>
        <div class="metric"><div class="k">CMF</div><div class="v ${d.cmf>=0?'v-up':'v-red'}">${fmt(d.cmf,3)}</div></div>
        <div class="metric"><div class="k">ATR %</div><div class="v v-muted">${fmt(d.atr_pct,2)}%</div></div>
        <div class="metric"><div class="k">Volume Ratio</div><div class="v v-muted">${fmt(d.vol_ratio,2)}x</div></div>
        <div class="metric"><div class="k">RS vs IHSG</div><div class="v ${rsCls}">${rsTxt}</div></div>
      </div>
    </div>

    <div class="card glass modish">
      <div class="sec"><span class="num">03B</span><div class="line"></div><span class="badge">Konfluensi Lanjutan</span></div>
      <div class="grid">
        <div class="metric"><div class="k">Squeeze</div><div class="v ${d.squeeze_on?'v-red':'v-up'}">${d.squeeze_on?'ON':'OFF'}</div></div>
        <div class="metric"><div class="k">Sqz Momentum</div><div class="v ${d.squeeze_mom>=0?'v-up':'v-red'}">${fmt(d.squeeze_mom,1)}</div></div>
        <div class="metric"><div class="k">Choppiness</div><div class="v ${d.chop>=61.8?'v-red':(d.chop<38?'v-up':'v-muted')}">${fmt(d.chop,1)}</div></div>
        <div class="metric"><div class="k">ADR %</div><div class="v v-muted">${fmt(d.adr_pct,2)}%</div></div>
        <div class="metric"><div class="k">ATR Persentil</div><div class="v v-muted">${fmt(d.atr_pctl,0)}</div></div>
        <div class="metric"><div class="k">Vol Regime</div><div class="v v-muted">${d.vol_regime||'-'}</div></div>
        <div class="metric"><div class="k">Anchored VWAP</div><div class="v ${d.price>=d.avwap?'v-up':'v-red'}">${idr(d.avwap)}</div></div>
        <div class="metric"><div class="k">MTF (D/W/M)</div><div class="v v-muted">${d.mtf||'-'}</div></div>
        <div class="metric"><div class="k">POC</div><div class="v v-muted">${idr(d.vp?d.vp.poc:0)}</div></div>
        <div class="metric"><div class="k">VAH</div><div class="v v-red">${idr(d.vp?d.vp.vah:0)}</div></div>
        <div class="metric"><div class="k">VAL</div><div class="v v-up">${idr(d.vp?d.vp.val:0)}</div></div>
        <div class="metric"><div class="k">Tren Bulanan</div><div class="v v-muted">${d.monthly_trend||'-'}</div></div>
      </div>
      ${(d.zones && d.zones.length)?'<div class="mono" style="margin-top:12px;color:#a3a3a3;font-size:11px">Zona: ' + d.zones.slice(-4).map(z => '<span style="color:' + (z.type==='demand'?'#26a69a':'#ef5350') + '">' + (z.type==='demand'?'DEMAND':'SUPPLY') + ' ' + fmt(z.bottom) + '-' + fmt(z.top) + '</span>').join(' &middot; ') + '</div>':''}
    </div>

    <div class="cols">
      <div class="card glass modish">
        <div class="sec"><span class="num">04</span><div class="line"></div><span class="badge">Level Kunci</span></div>
        <div class="grid">
          <div class="metric"><div class="k">Support</div><div class="v v-up">${idr(d.support)}</div></div>
          <div class="metric"><div class="k">Resistance</div><div class="v v-red">${idr(d.resistance)}</div></div>
          <div class="metric"><div class="k">Pivot PP</div><div class="v v-muted">${idr(Math.round(d.pivot.pp))}</div></div>
          <div class="metric"><div class="k">Pivot R1 / S1</div><div class="v v-muted">${fmt(d.pivot.r1,0)}/${fmt(d.pivot.s1,0)}</div></div>
          <div class="metric"><div class="k">Fib 0.382</div><div class="v v-muted">${fmt(d.fib["0.382"],0)}</div></div>
          <div class="metric"><div class="k">Fib 0.618</div><div class="v v-muted">${fmt(d.fib["0.618"],0)}</div></div>
          <div class="metric"><div class="k">Fib Ext 1.618</div><div class="v v-up">${fmt(d.fib["ext_1.618"],0)}</div></div>
        </div>
      </div>
      <div class="card glass modish">
        <div class="sec"><span class="num">05</span><div class="line"></div><span class="badge">Score Breakdown</span></div>
        <div style="margin-top:4px">${comps}</div>
      </div>
    </div>

    <div class="card glass modish">
      <div class="sec"><span class="num">06</span><div class="line"></div><span class="badge">Confluence Checklist</span></div>
      <div class="checks">${checks}</div>
      ${d.patterns.length?`<div class="mono" style="margin-top:14px;color:#7c8c83;font-size:12px">Pola candle: <b style="color:#0f1712">${d.patterns.join(", ")}</b></div>`:""}
      ${d.divergences.length?`<div class="mono" style="margin-top:6px;color:#7c8c83;font-size:12px">Divergence: <b style="color:#0f1712">${d.divergences.join(", ")}</b></div>`:""}
    </div>

    <div class="cols">
      <div class="card glass modish"><div class="sec"><span class="num">07</span><div class="line"></div><span class="badge">Bullish Factors</span></div><ul class="list">${reasons}</ul></div>
      <div class="card glass modish"><div class="sec"><span class="num">08</span><div class="line"></div><span class="badge">Warnings</span></div><ul class="list warn">${warns}</ul></div>
    </div>

    <div class="card glass modish">
      <div class="sec"><span class="num">09</span><div class="line"></div><span class="badge">Technical Chart</span>
        <button class="btn ghost" onclick="exportCsv()" style="margin-left:auto;padding:7px 14px">Export CSV</button>
        <button class="btn ghost" onclick="window.print()" style="padding:7px 14px">Print</button>
        <a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(d.tv_symbol)}" target="_blank"
           class="btn ghost" style="text-decoration:none;padding:7px 14px">TradingView</a>
      </div>
      <div id="liveChart" class="lwchart" style="border:0;border-radius:0"></div>
    </div>

    <div id="fundCard"></div>
    <div id="mlCard"></div>
    <div id="newsCard"></div>`;
  lastAnalysis = d;
  loadFundamental(d.ticker);
  loadMl(d.ticker);
  loadNews(d.ticker);
  document.querySelector("#panel-analisis").scrollIntoView({behavior:"smooth", block:"start"});
  quoteTicker = d.ticker;
  pollQuote();
  loadChart("analysis", "#liveChart", d.ticker, current.interval, $("#refresh").checked);
}

async function pollQuote(){
  if(!quoteTicker) return;
  try{
    const r = await fetch(`/api/quote?ticker=${encodeURIComponent(quoteTicker)}`);
    const q = await r.json();
    if(q.error || q.last==null) return;
    const p = document.getElementById("livePrice");
    const c = document.getElementById("liveChg");
    const s = document.getElementById("liveStamp");
    const dot = document.getElementById("liveDot");
    if(p) p.textContent = idr(q.last);
    if(c) c.innerHTML = chg(q.change_1d);
    if(dot) dot.style.display = "inline-block";
    if(s) s.textContent = "· LIVE " + (q.source||"") + " " + new Date().toLocaleTimeString("id-ID",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  }catch(e){}
}
setInterval(pollQuote, 10000);

/* keep live charts moving: refresh last candle from live quote */
setInterval(async () => {
  const jobs = [];
  if (document.querySelector("#panel-analisis").classList.contains("active") && charts.analysis) jobs.push(charts.analysis);
  if (document.querySelector("#panel-live").classList.contains("active") && charts.live) jobs.push(charts.live);
  for (const api of jobs) {
    if (!api.ticker) continue;
    try {
      const r = await fetch(`/api/quote?ticker=${encodeURIComponent(api.ticker)}`);
      const q = await r.json();
      if (!q.error && q.last != null) ChartKit.updateLast(api, q.last, q.day_high, q.day_low);
    } catch (e) {}
  }
}, 10000);

$("#scList").onchange = () => { $("#customWrap").style.display = $("#scList").value==="custom" ? "flex":"none"; };
$("#scRun").onclick = runScreen;
let _scCancel = false;
(function(){ const b=document.getElementById("scCancelBtn"); if(b) b.onclick=()=>{ _scCancel=true; }; })();
function showScProgress(done, total, show){
  const box = $("#scProgress"); if(!box) return;
  box.style.display = show ? "flex" : "none";
  const pct = total ? Math.round(done/total*100) : 0;
  const bar = box.querySelector(".bar > i"); if(bar) bar.style.width = pct+"%";
  const txt = $("#scProgressText"); if(txt) txt.textContent = done+" / "+total+" dipindai ("+pct+"%)";
}
function renderScanRows(dataRows, totalUniverse, scanned){
  if(!dataRows.length){ $("#scResult").innerHTML = '<div class="empty">Tidak ada hasil.</div>'; return; }
  const rows = dataRows.map(x=>{
    const sc = signalClass(x.Signal);
    const valM = x.Value ? (x.Value/1e9).toFixed(1)+" M" : "-";
    return `<tr onclick="pick('${x.Ticker}')">
      <td style="font-weight:700">${x.Ticker}</td>
      <td style="color:#a3a3a3">${x.Sector||"-"}</td>
      <td>${fmt(x.Price)}</td>
      <td><span class="tag s-${sc}">${x.Signal}</span></td>
      <td style="color:#a3a3a3">${x.Action}</td>
      <td>${x.Score}</td><td>${x.Conf}</td>
      <td style="color:${x.Grade[0]==='A'?'#26a69a':'#a3a3a3'}">${x.Grade}</td>
      <td style="color:#a3a3a3">${x.Trend}</td><td>${x.Wk}</td>
      <td style="color:${String(x.MTF).includes('Bullish')?'#26a69a':'#a3a3a3'}">${x.MTF||"-"}</td>
      <td>${fmt(x.ADX,1)}</td><td style="color:${x.ST==='UP'?'#26a69a':'#ef5350'}">${x.ST}</td>
      <td>${fmt(x.RSI,1)}</td><td>${fmt(x.Vol,2)}</td>
      <td style="color:${x.Sqz==='ON'?'#ef5350':'#a3a3a3'}">${x.Sqz}</td>
      <td>${fmt(x.Chop,1)}</td>
      <td>${valM}</td>
      <td>${fmt(x.TP1)}</td><td style="color:#ef5350">${fmt(x.SL)}</td>
      <td>1:${fmt(x.RR,1)}</td><td>${fmt(x["ATR%"],2)}%</td>
    </tr>`;
  }).join("");
  $("#scResult").innerHTML = `<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px">${dataRows.length} hasil dari ${totalUniverse} saham (dipindai ${scanned}) &middot; klik baris untuk detail</div>
    <div style="overflow-x:auto"><table>
    <thead><tr><th>Ticker</th><th>Sektor</th><th>Harga</th><th>Sinyal</th><th>Aksi</th><th>Skor</th><th>Conf</th><th>Grade</th><th>Tren</th><th>Wk</th><th>MTF</th><th>ADX</th><th>ST</th><th>RSI</th><th>Vol</th><th>Sqz</th><th>Chop</th><th>Nilai</th><th>TP1</th><th>SL</th><th>RR</th><th>ATR%</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}
async function runScreen(){
  let list = $("#scList").value;
  if(list==="custom"){ list = $("#scCustom").value.trim(); if(!list){ showStatus("Isi daftar dulu"); return; } }
  _scCancel = false;
  $("#scRun").disabled = true;
  const minS=$("#scMin").value, minC=$("#scConf").value, sec=$("#scSector").value,
        mv=$("#scValue").value||0, bull=$("#scBull").checked?1:0, rfr=$("#scRefresh").checked?1:0;
  try{
    showStatus("Menyiapkan daftar saham...", true);
    const tinfo = await fetchJSON(`/api/tickers?list=${encodeURIComponent(list)}`);
    const tickers = (tinfo && tinfo.tickers) || [];
    if(!tickers.length){ $("#scResult").innerHTML='<div class="empty">Daftar saham kosong.</div>'; return; }
    const chunkSize = 100;
    let merged = [], scanned = 0;
    showScProgress(0, tickers.length, true);
    for(let i=0;i<tickers.length;i+=chunkSize){
      if(_scCancel) break;
      const chunk = tickers.slice(i, i+chunkSize);
      const url = `/api/screen?list=${encodeURIComponent(chunk.join(","))}&top=1000&min_score=${minS}&min_conf=${minC}&sector=${encodeURIComponent(sec)}&min_value=${mv}&only_bullish=${bull}&refresh=${rfr}`;
      try{ const d = await fetchJSON(url, {retries:2}); merged = merged.concat(d.rows||[]); }catch(e){}
      scanned += chunk.length;
      showScProgress(scanned, tickers.length, true);
    }
    showScProgress(scanned, tickers.length, false);
    if($("#scSqz").checked) merged = merged.filter(x => x.Sqz==="OFF" && Number(x.SqzMom)>0);
    merged.sort((a,b)=> (b.Score-a.Score) || (b.Conf-a.Conf));
    const top = parseInt($("#scTop").value||"0",10);
    const dataRows = (top>0) ? merged.slice(0, top) : merged;
    renderScanRows(dataRows, tickers.length, scanned);
    showStatus(_scCancel ? "Dibatalkan" : "Selesai");
  }catch(e){
    $("#scResult").innerHTML = '<div class="empty">Gagal: '+e.message+'. Server mungkin sedang bangun — coba lagi.</div>';
    showStatus("Gagal");
  }
  finally{ $("#scRun").disabled=false; }
}

function pick(t){
  $("#ticker").value = t;
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(x=>x.classList.remove("active"));
  document.querySelector('.tab[data-tab="analisis"]').classList.add("active");
  $("#panel-analisis").classList.add("active");
  analyze();
}

let tvInterval = "1d";
function loadLiveChart(){
  const t = ($("#tvSym").value || current.ticker).trim().toUpperCase();
  loadChart("live", "#tv_chart", t, tvInterval, false);
}
$("#tvGo").onclick = loadLiveChart;
$("#tvSym").addEventListener("keydown", e => { if(e.key==="Enter") loadLiveChart(); });
document.querySelectorAll(".tvbtn").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tvbtn").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); tvInterval = TV_INT[b.dataset.i] || "1d"; loadLiveChart();
});

/* ---------- Export & reporting ---------- */
let lastAnalysis = null;
function exportCsv(){
  const d = lastAnalysis;
  if(!d){ showStatus("Belum ada analisis"); return; }
  const rows = [
    ["Ticker", d.ticker], ["Interval", d.interval], ["Harga", d.price],
    ["Perubahan 1D (%)", d.change_1d], ["Sinyal", d.signal], ["Aksi", d.action],
    ["Skor", d.score], ["Confidence", d.confidence], ["Grade", d.grade],
    ["Tren", d.trend], ["Tren Mingguan", d.weekly_trend], ["Tren Bulanan", d.monthly_trend],
    ["Regime", d.regime], ["MTF", d.mtf],
    ["Entry", d.entry], ["Zona Beli", d.buy_zone_low + " - " + d.buy_zone_high],
    ["Stop Loss", d.stop_loss], ["Trailing Stop", d.stop_trail],
    ["TP1", d.tp1], ["TP2", d.tp2], ["TP3", d.tp3],
    ["RR1", d.rr1], ["RR2", d.rr2], ["RR3", d.rr3],
    ["RSI", d.rsi], ["ADX", d.adx], ["ATR%", d.atr_pct],
    ["Squeeze", d.squeeze_on ? "ON" : "OFF"], ["Sqz Momentum", d.squeeze_mom],
    ["Choppiness", d.chop], ["ADR%", d.adr_pct], ["Vol Regime", d.vol_regime],
    ["Anchored VWAP", d.avwap],
    ["POC", d.vp ? d.vp.poc : ""], ["VAH", d.vp ? d.vp.vah : ""], ["VAL", d.vp ? d.vp.val : ""],
    ["Support", d.support], ["Resistance", d.resistance],
  ];
  const csv = "Metrik,Nilai\n" + rows.map(r => '"' + r[0] + '","' + r[1] + '"').join("\n");
  const blob = new Blob([csv], {type:"text/csv;charset=utf-8;"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = d.ticker + "_analisis_" + new Date().toISOString().slice(0,10) + ".csv";
  a.click();
  showStatus("CSV diunduh");
}

/* ---------- Backtest ---------- */
$("#btRun").onclick = runBacktest;
async function runBacktest(){
  const t = ($("#btTicker").value||"").trim().toUpperCase();
  if(!t) return;
  showStatus("Menjalankan backtest...", true); $("#btRun").disabled = true;
  try{
    const url = `/api/backtest?ticker=${encodeURIComponent(t)}&min_score=${$("#btMin").value}&tp_rr=${$("#btTp").value}&sl_mult=${$("#btSl").value}&max_hold=${$("#btHold").value}&fee_b=${$("#btFeeB").value}&fee_s=${$("#btFeeS").value}&slip=${$("#btSlip").value}`;
    const r = await fetch(url); const d = await r.json();
    if(d.error) throw new Error(d.error);
    const pct = (v) => (Number(v)*100).toFixed(1) + "%";
    const pf = d.profit_factor==null ? "~" : Number(d.profit_factor).toFixed(2);
    const trades = (d.trades||[]).map(t => `<tr>
      <td>${String(t.entry_date).slice(0,10)}</td>
      <td>${String(t.exit_date).slice(0,10)}</td>
      <td>${fmt(t.entry)}</td><td>${fmt(t.exit)}</td>
      <td>${t.bars}</td>
      <td style="color:${t.reason==='TP'?'#26a69a':(t.reason==='SL'?'#ef5350':'#a3a3a3')}">${t.reason}</td>
      <td style="color:${t.return_pct>=0?'#26a69a':'#ef5350'}">${t.return_pct>=0?'+':''}${fmt(t.return_pct,2)}%</td>
    </tr>`).join("");
    $("#btResult").innerHTML = `
      <div class="grid">
        <div class="metric hl"><div class="k">Total Return</div><div class="v ${d.total_return>=0?'v-up':'v-red'}">${pct(d.total_return)}</div></div>
        <div class="metric"><div class="k">Buy &amp; Hold</div><div class="v v-muted">${pct(d.buy_hold_return)}</div></div>
        <div class="metric"><div class="k">Jumlah Trade</div><div class="v v-white">${d.n_trades}</div></div>
        <div class="metric"><div class="k">Win Rate</div><div class="v v-white">${pct(d.win_rate)}</div></div>
        <div class="metric"><div class="k">Profit Factor</div><div class="v v-up">${pf}</div></div>
        <div class="metric"><div class="k">Max Drawdown</div><div class="v v-red">${pct(d.max_drawdown)}</div></div>
        <div class="metric"><div class="k">Expectancy</div><div class="v ${d.expectancy>=0?'v-up':'v-red'}">${pct(d.expectancy)}</div></div>
        <div class="metric"><div class="k">Avg Win</div><div class="v v-up">${pct(d.avg_win)}</div></div>
        <div class="metric"><div class="k">Avg Loss</div><div class="v v-red">${pct(d.avg_loss)}</div></div>
      </div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 8px">Daftar Trade</div>
      <div style="overflow-x:auto"><table>
        <thead><tr><th>Entry</th><th>Exit</th><th>Harga Entry</th><th>Harga Exit</th><th>Bar</th><th>Alasan</th><th>Return</th></tr></thead>
        <tbody>${trades || '<tr><td colspan="7" style="text-align:center;color:#737373">Tidak ada trade</td></tr>'}</tbody>
      </table></div>`;
    const rk = d.risk || {};
    const rcard = (label, value, cls) => '<div class="metric"><div class="k">' + label + '</div><div class="v ' + (cls || 'v-muted') + '">' + value + '</div></div>';
    const riskHtml = '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 8px">Metrik Risiko</div><div class="grid">'
      + rcard('Sharpe', rk.sharpe, rk.sharpe > 0 ? 'v-up' : 'v-red')
      + rcard('Sortino', rk.sortino, rk.sortino > 0 ? 'v-up' : 'v-red')
      + rcard('Calmar', rk.calmar, rk.calmar > 0 ? 'v-up' : 'v-red')
      + rcard('Max Drawdown', (rk.max_dd != null ? rk.max_dd + '%' : '-'), 'v-red')
      + rcard('VaR 95%', (rk.var95 != null ? rk.var95 + '%' : '-'), 'v-muted')
      + rcard('CVaR 95%', (rk.cvar95 != null ? rk.cvar95 + '%' : '-'), 'v-red')
      + rcard('Volatilitas (ann)', (rk.ann_vol != null ? rk.ann_vol + '%' : '-'), 'v-muted')
      + rcard('Kelly', (rk.kelly != null ? (rk.kelly * 100).toFixed(1) + '%' : '-'), rk.kelly > 0 ? 'v-up' : 'v-red')
      + '</div>'
      + '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 8px">Equity Curve</div><div id="btEquity" class="lwchart" style="border:0;border-radius:0"></div>';
    $("#btResult").insertAdjacentHTML("beforeend", riskHtml);
    ChartKit.load(() => { const el = document.getElementById("btEquity"); if (el && d.dates && d.equity_curve) ChartKit.equity(el, d.dates, d.equity_curve); });
    showStatus("Selesai");
  }catch(e){ $("#btResult").innerHTML = '<div class="empty">Gagal: ' + e.message + '</div>'; showStatus("Gagal"); }
  finally{ $("#btRun").disabled=false; }
}

/* ---------- Accuracy / edge study ---------- */
$("#acRun").onclick = runAccuracy;
async function runAccuracy(){
  const t=($("#acTicker").value||"").trim().toUpperCase(); if(!t) return;
  showStatus("Mengukur akurasi...", true); $("#acRun").disabled=true;
  try{
    const r=await fetch(`/api/accuracy?ticker=${encodeURIComponent(t)}&horizon=${$("#acHorizon").value||10}`);
    const d=await r.json(); if(d.error) throw new Error(d.error);
    const pct=(v)=> v==null?"-":(Number(v)*100).toFixed(1)+"%";
    const num=(v)=> v==null?"-":Number(v).toFixed(2);
    const calRows=(d.calibration||[]).map(x=>'<tr><td style="text-align:left">'+x.bucket+'</td><td>'+x.n+'</td><td>'+pct(x.win_rate)+'</td><td>'+num(x.avg_ret)+'%</td><td class="'+(x.edge>=0?'v-up':'v-red')+'">'+(x.edge==null?'':(x.edge>=0?'+':'')+pct(x.edge))+'</td></tr>').join("");
    const agrRows=(d.agreement||[]).map(x=>'<tr><td style="text-align:left">'+x.bucket+'</td><td>'+x.n+'</td><td>'+pct(x.win_rate)+'</td><td>'+num(x.avg_ret)+'%</td></tr>').join("");
    const facRows=(d.factors||[]).map(x=>'<tr><td style="text-align:left">'+x.factor+'</td><td>'+x.n+'</td><td>'+pct(x.win_rate)+'</td><td>'+num(x.avg_ret)+'%</td><td class="'+(x.edge>=0?'v-up':'v-red')+'">'+(x.edge>=0?'+':'')+pct(x.edge)+'</td></tr>').join("");
    $("#acResult").innerHTML=`
      <div class="grid">
        <div class="metric hl"><div class="k">Base Win Rate</div><div class="v v-white">${pct(d.base_win_rate)}</div></div>
        <div class="metric"><div class="k">Base Avg Return</div><div class="v v-muted">${num(d.base_avg_ret)}%</div></div>
        <div class="metric"><div class="k">Sampel</div><div class="v v-white">${d.samples}</div></div>
        <div class="metric"><div class="k">Horizon</div><div class="v v-muted">${d.horizon} bar</div></div>
      </div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Kalibrasi Skor vs Hasil (${d.horizon} bar)</div>
      <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Bucket Skor</th><th>N</th><th>Win Rate</th><th>Avg Fwd Ret</th><th>Edge</th></tr></thead><tbody>${calRows}</tbody></table></div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Konfluensi: jumlah faktor setuju vs hasil</div>
      <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Faktor Setuju</th><th>N</th><th>Win Rate</th><th>Avg Fwd Ret</th></tr></thead><tbody>${agrRows}</tbody></table></div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Edge per Indikator (diurutkan)</div>
      <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Faktor</th><th>N</th><th>Win Rate</th><th>Avg Fwd Ret</th><th>Edge</th></tr></thead><tbody>${facRows}</tbody></table></div>`;
    showStatus("Selesai");
  }catch(e){ $("#acResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ $("#acRun").disabled=false; }
}

/* ---------- Portfolio: watchlist, positions, alerts, history ---------- */
const LS = {
  get(k, def){ try{ const v = JSON.parse(localStorage.getItem(k)); return v==null ? def : v; }catch(e){ return def; } },
  set(k, v){ try{ localStorage.setItem(k, JSON.stringify(v)); }catch(e){} },
};
let watchlist = LS.get("sbl_watchlist", ["BBCA","BBRI","TLKM"]);
let positions = LS.get("sbl_positions", []);
let alerts = LS.get("sbl_alerts", []);
const posQuotes = {};
const alertState = {};

function renderWatchlist(){
  const el = $("#wlList");
  if(!watchlist.length){ el.innerHTML = '<div class="empty" style="padding:24px">Watchlist kosong.</div>'; return; }
  el.innerHTML = watchlist.map(t => '<div class="check" style="justify-content:space-between">'
    + '<span style="cursor:pointer" onclick="pick(\'' + t + '\')">' + t + '</span>'
    + '<span><span class="mono" id="wl-' + t + '" style="color:#a3a3a3">' + (posQuotes[t]!=null?idr(posQuotes[t]):"-") + '</span>'
    + '<button class="btn ghost" style="padding:3px 8px;margin-left:8px" onclick="wlRemove(\'' + t + '\')">x</button></span></div>').join("");
}
function wlAdd(){ const t=($("#wlInput").value||"").trim().toUpperCase(); if(!t) return;
  if(!watchlist.includes(t)){ watchlist.push(t); LS.set("sbl_watchlist", watchlist); renderWatchlist(); pollPortfolio(); }
  $("#wlInput").value=""; }
function wlRemove(t){ watchlist = watchlist.filter(x=>x!==t); LS.set("sbl_watchlist", watchlist); renderWatchlist(); }
$("#wlAdd").onclick = wlAdd;
$("#wlInput").addEventListener("keydown", e => { if(e.key==="Enter") wlAdd(); });

function renderPositions(){
  const el = $("#posList");
  if(!positions.length){ el.innerHTML = '<div class="empty" style="padding:24px">Belum ada posisi.</div>'; return; }
  el.innerHTML = '<div style="overflow-x:auto"><table>'
    + '<thead><tr><th>Kode</th><th>Entry</th><th>Lot</th><th>Harga</th><th>P/L</th><th>Stop</th><th>TP</th><th></th></tr></thead><tbody>'
    + positions.map((p,i)=>{
        const q = posQuotes[p.ticker];
        const pl = (q!=null) ? (q-p.entry)*p.lots*100 : null;
        const plPct = (q!=null && p.entry) ? (q/p.entry-1)*100 : null;
        const cls = pl==null ? "" : (pl>=0?"v-up":"v-red");
        return '<tr>'
          + '<td style="font-weight:700;cursor:pointer" onclick="pick(\'' + p.ticker + '\')">' + p.ticker + '</td>'
          + '<td>' + fmt(p.entry) + '</td><td>' + p.lots + '</td>'
          + '<td>' + (q!=null?idr(q):"-") + '</td>'
          + '<td class="' + cls + '">' + (pl!=null ? (pl>=0?'+':'')+idr(pl)+' ('+(plPct>=0?'+':'')+fmt(plPct,2)+'%)' : "-") + '</td>'
          + '<td style="color:#ef5350">' + (p.sl?fmt(p.sl):"-") + '</td>'
          + '<td style="color:#26a69a">' + (p.tp?fmt(p.tp):"-") + '</td>'
          + '<td><button class="btn ghost" style="padding:3px 8px" onclick="posRemove(' + i + ')">x</button></td></tr>';
      }).join("") + '</tbody></table></div>';
}
function posAdd(){
  const ticker=($("#posTicker").value||"").trim().toUpperCase();
  const entry=parseFloat($("#posEntry").value); const lots=parseInt($("#posLots").value||"0");
  if(!ticker||!entry){ showStatus("Isi kode & entry"); return; }
  positions.push({ticker, entry, lots, sl:parseFloat($("#posSl").value)||0, tp:parseFloat($("#posTp").value)||0});
  LS.set("sbl_positions", positions); renderPositions(); pollPortfolio();
  $("#posTicker").value=""; $("#posEntry").value=""; $("#posSl").value=""; $("#posTp").value="";
}
function posRemove(i){ positions.splice(i,1); LS.set("sbl_positions", positions); renderPositions(); }
$("#posAdd").onclick = posAdd;

function renderAlerts(){
  const el = $("#alList");
  if(!alerts.length){ el.innerHTML = '<div class="empty" style="padding:24px">Belum ada alert.</div>'; return; }
  el.innerHTML = alerts.map((a,i)=>{
    const q = posQuotes[a.ticker];
    const fired = alertState[i];
    return '<div class="check" style="justify-content:space-between">'
      + '<span>' + a.ticker + ' ' + (a.dir==='above'?'&ge;':'&le;') + ' ' + fmt(a.price) + ' ' + (fired?'<b style="color:#ef4444">TRIGGERED</b>':'') + '</span>'
      + '<span><span class="mono" style="color:#a3a3a3">' + (q!=null?idr(q):"-") + '</span>'
      + '<button class="btn ghost" style="padding:3px 8px;margin-left:8px" onclick="alRemove(' + i + ')">x</button></span></div>';
  }).join("");
}
function alAdd(){
  const ticker=($("#alTicker").value||"").trim().toUpperCase();
  const price=parseFloat($("#alPrice").value); const dir=$("#alDir").value;
  if(!ticker||!price){ showStatus("Isi kode & harga"); return; }
  alerts.push({ticker, price, dir}); LS.set("sbl_alerts", alerts); renderAlerts(); pollPortfolio();
  $("#alTicker").value=""; $("#alPrice").value="";
}
function alRemove(i){ alerts.splice(i,1); LS.set("sbl_alerts", alerts); renderAlerts(); }
$("#alAdd").onclick = alAdd;
$("#alNotify").onclick = () => {
  if(window.Notification && Notification.permission !== "granted"){
    Notification.requestPermission().then(p => showStatus(p==="granted" ? "Notifikasi aktif" : "Notifikasi ditolak"));
  } else showStatus("Notifikasi siap/ tidak didukung");
};

async function loadHistory(){
  try{
    const r = await fetch("/api/history?limit=40"); const d = await r.json();
    const rows = (d.rows||[]).map(x => '<tr>'
      + '<td>' + x.time + '</td>'
      + '<td style="font-weight:700;cursor:pointer" onclick="pick(\'' + x.ticker + '\')">' + x.ticker + '</td>'
      + '<td><span class="tag s-' + signalClass(x.signal) + '">' + x.signal + '</span></td>'
      + '<td>' + x.score + '</td><td>' + x.confidence + '</td><td>' + x.grade + '</td><td>' + fmt(x.price) + '</td></tr>').join("");
    $("#histList").innerHTML = rows ? '<div style="overflow-x:auto"><table>'
      + '<thead><tr><th>Waktu</th><th>Kode</th><th>Sinyal</th><th>Skor</th><th>Conf</th><th>Grade</th><th>Harga</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table></div>'
      : '<div class="empty" style="padding:24px">Belum ada riwayat (analisis manual akan tercatat).</div>';
  }catch(e){ $("#histList").innerHTML = '<div class="empty">Gagal memuat riwayat.</div>'; }
}
$("#histClear").onclick = () => showStatus("Riwayat disimpan di server (reset saat restart)");

async function pollPortfolio(){
  const tickers = Array.from(new Set([].concat(watchlist, positions.map(p=>p.ticker), alerts.map(a=>a.ticker)))).filter(Boolean);
  for(const t of tickers){
    try{
      const r = await fetch(`/api/quote?ticker=${encodeURIComponent(t)}`); const q = await r.json();
      if(!q.error && q.last!=null) posQuotes[t] = q.last;
    }catch(e){}
  }
  watchlist.forEach(t => { const el=document.getElementById("wl-"+t); if(el && posQuotes[t]!=null) el.textContent = idr(posQuotes[t]); });
  renderPositions();
  let changed = false;
  alerts.forEach((a,i) => {
    const q = posQuotes[a.ticker];
    if(q==null) return;
    const hit = a.dir==="above" ? q>=a.price : q<=a.price;
    if(hit && !alertState[i]){ alertState[i]=true; changed=true; fireAlert(a,q); }
  });
  if(changed) renderAlerts();
}
function fireAlert(a, q){
  showStatus('ALERT ' + a.ticker + ' ' + (a.dir==='above'?'>= ':'<= ') + fmt(a.price) + ' (now ' + fmt(q) + ')', false);
  if(window.Notification && Notification.permission==="granted"){
    try{ new Notification("IDX " + a.ticker, { body: "Harga " + fmt(q) + " " + (a.dir==='above'?'>= ':'<= ') + fmt(a.price) }); }catch(e){}
  }
}
function refreshPortfolio(){ renderWatchlist(); renderPositions(); renderAlerts(); loadHistory(); pollPortfolio(); }

/* ---------- Fundamental ---------- */
async function loadFundamental(t){
  const el = document.getElementById("fundCard"); if(!el) return;
  el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">10</span><div class="line"></div><span class="badge">Fundamental</span></div><div class="empty">Memuat fundamental...</div></div>';
  try{
    const f = await (await fetch('/api/fundamental?ticker=' + encodeURIComponent(t))).json();
    if(f.error) throw new Error(f.error);
    const num=(v)=> v==null?"-":Number(v).toFixed(2);
    const pct=(v)=> v==null?"-":(Number(v)*100).toFixed(2)+"%";
    const dy=(v)=> v==null?"-":Number(v).toFixed(2)+"%";
    const capv=(v)=> v==null?"-":(Number(v)/1e12).toFixed(2)+" T";
    el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">10</span><div class="line"></div><span class="badge">Fundamental</span></div><div class="grid">'
      + '<div class="metric"><div class="k">Nama</div><div class="v v-white" style="font-size:13px">' + (f.name || t) + '</div></div>'
      + '<div class="metric"><div class="k">Market Cap</div><div class="v v-muted">' + capv(f.market_cap) + '</div></div>'
      + '<div class="metric"><div class="k">PER</div><div class="v v-muted">' + num(f.pe) + '</div></div>'
      + '<div class="metric"><div class="k">PBV</div><div class="v v-muted">' + num(f.pb) + '</div></div>'
      + '<div class="metric"><div class="k">ROE</div><div class="v ' + ((f.roe||0)>=0.1?'v-up':'v-muted') + '">' + pct(f.roe) + '</div></div>'
      + '<div class="metric"><div class="k">DER</div><div class="v v-muted">' + num(f.der) + '</div></div>'
      + '<div class="metric"><div class="k">EPS</div><div class="v v-muted">' + num(f.eps) + '</div></div>'
      + '<div class="metric"><div class="k">Div Yield</div><div class="v v-up">' + dy(f.dividend_yield) + '</div></div>'
      + '<div class="metric"><div class="k">Profit Margin</div><div class="v v-muted">' + pct(f.profit_margin) + '</div></div>'
      + '<div class="metric"><div class="k">Beta</div><div class="v v-muted">' + num(f.beta) + '</div></div>'
      + '<div class="metric"><div class="k">52w High</div><div class="v v-red">' + fmt(f.high_52w) + '</div></div>'
      + '<div class="metric"><div class="k">52w Low</div><div class="v v-up">' + fmt(f.low_52w) + '</div></div>'
      + '</div></div>';
  }catch(e){ el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">10</span><div class="line"></div><span class="badge">Fundamental</span></div><div class="empty">Gagal memuat fundamental.</div></div>'; }
}

/* ---------- Walk-forward ---------- */
$("#btWfRun").onclick = runWalkforward;
async function runWalkforward(){
  const t=($("#btTicker").value||"").trim().toUpperCase(); if(!t) return;
  showStatus("Walk-forward...", true);
  try{
    const r=await fetch('/api/walkforward?ticker=' + encodeURIComponent(t) + '&min_score=' + $("#btMin").value + '&tp_rr=' + $("#btTp").value + '&sl_mult=' + $("#btSl").value + '&max_hold=' + $("#btHold").value);
    const d=await r.json(); if(d.error) throw new Error(d.error);
    const pct=(v)=> v==null?"-":(Number(v)*100).toFixed(1)+"%";
    const rows=(d.folds||[]).map(x=> x.error ? '<tr><td>'+x.fold+'</td><td colspan="7" style="color:#ef5350">'+x.error+'</td></tr>' :
      '<tr><td>'+x.fold+'</td><td>'+x.start+'</td><td>'+x.end+'</td><td>'+x.n_trades+'</td>'
      +'<td class="'+(x.total_return>=0?'v-up':'v-red')+'">'+pct(x.total_return)+'</td>'
      +'<td class="'+(x.buy_hold>=0?'v-up':'v-red')+'">'+pct(x.buy_hold)+'</td>'
      +'<td>'+pct(x.win_rate)+'</td>'
      +'<td class="'+(x.max_dd>=0?'':'v-red')+'">'+pct(x.max_dd)+'</td></tr>').join("");
    $("#btWf").innerHTML = '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px">Walk-forward (segmen out-of-sample)</div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th>Fold</th><th>Mulai</th><th>Selesai</th><th>Trade</th><th>Return</th><th>B&amp;H</th><th>Win</th><th>MaxDD</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
    showStatus("Selesai");
  }catch(e){ $("#btWf").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
}

/* ---------- Market dashboard ---------- */
$("#mkRun").onclick = runMarket;
async function runMarket(){
  const list=$("#mkList").value; if(!list) return;
  showStatus("Mengambil data pasar...", true); $("#mkRun").disabled=true;
  try{
    const d=await (await fetch('/api/market?list=' + encodeURIComponent(list))).json();
    if(d.error) throw new Error(d.error);
    const pct=(v)=> v==null?"-":(Number(v)).toFixed(2)+"%";
    const ih=d.ihsg||{}; const br=d.breadth||{};
    const heat=(d.sectors||[]).map(s=>'<tr><td style="text-align:left">'+s.sector+'</td><td>'+s.n+'</td>'
      +'<td class="'+(s.chg_1d>=0?'v-up':'v-red')+'">'+pct(s.chg_1d)+'</td>'
      +'<td class="'+(s.chg_5d>=0?'v-up':'v-red')+'">'+pct(s.chg_5d)+'</td>'
      +'<td class="'+(s.chg_20d>=0?'v-up':'v-red')+'">'+pct(s.chg_20d)+'</td>'
      +'<td>'+s.breadth+'%</td></tr>').join("");
    const rs=(d.rs_ranking||[]).map(x=>'<tr onclick="pick(\''+x.ticker+'\')" style="cursor:pointer"><td style="text-align:left;font-weight:700">'+x.ticker+'</td><td style="text-align:left;color:#a3a3a3">'+x.sector+'</td>'
      +'<td class="'+(x.chg_1d>=0?'v-up':'v-red')+'">'+pct(x.chg_1d)+'</td>'
      +'<td class="'+(x.chg_20d>=0?'v-up':'v-red')+'">'+pct(x.chg_20d)+'</td></tr>').join("");
    $("#mkResult").innerHTML =
      '<div class="grid">'
      +'<div class="metric hl"><div class="k">IHSG</div><div class="v v-white">'+fmt(ih.price)+'</div></div>'
      +'<div class="metric"><div class="k">Regime</div><div class="v '+(ih.regime==='Bullish'?'v-up':(ih.regime==='Bearish'?'v-red':'v-muted'))+'">'+(ih.regime||'-')+'</div></div>'
      +'<div class="metric"><div class="k">IHSG 1D</div><div class="v '+(ih.ret_1d>=0?'v-up':'v-red')+'">'+pct(ih.ret_1d)+'</div></div>'
      +'<div class="metric"><div class="k">IHSG 20D</div><div class="v '+(ih.ret_20d>=0?'v-up':'v-red')+'">'+pct(ih.ret_20d)+'</div></div>'
      +'<div class="metric"><div class="k">Breadth &gt; MA50</div><div class="v v-muted">'+(br.pct_above_ma50)+'%</div></div>'
      +'<div class="metric"><div class="k">Naik / Turun</div><div class="v v-muted">'+br.advancers+' / '+br.decliners+'</div></div>'
      +'</div>'
      +'<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Heatmap Sektor</div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Sektor</th><th>N</th><th>1D</th><th>5D</th><th>20D</th><th>Breadth</th></tr></thead><tbody>'+heat+'</tbody></table></div>'
      +'<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Relative Strength Ranking (20D)</div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Kode</th><th style="text-align:left">Sektor</th><th>1D</th><th>20D</th></tr></thead><tbody>'+rs+'</tbody></table></div>';
    showStatus("Selesai");
  }catch(e){ $("#mkResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ $("#mkRun").disabled=false; }
}

/* ---------- Risk calculator ---------- */
$("#rkCalc").onclick = () => {
  const cap=parseFloat($("#rkCapital").value)||0, rp=parseFloat($("#rkRisk").value)||0;
  const e=parseFloat($("#rkEntry").value), s=parseFloat($("#rkStop").value);
  if(!cap||!e||!s||e<=s){ $("#rkResult").innerHTML='<div class="empty" style="padding:20px">Isi entry &gt; stop.</div>'; return; }
  const riskAmt=cap*rp/100, perLot=(e-s)*100, lots=Math.floor(riskAmt/perLot), shares=lots*100, val=shares*e;
  $("#rkResult").innerHTML='<div class="grid">'
    +'<div class="metric hl"><div class="k">Saran Lot</div><div class="v v-white">'+fmt(lots)+'</div></div>'
    +'<div class="metric"><div class="k">Saham</div><div class="v v-muted">'+fmt(shares)+'</div></div>'
    +'<div class="metric"><div class="k">Nilai Posisi</div><div class="v v-muted">'+idr(val)+'</div></div>'
    +'<div class="metric"><div class="k">Risiko Max</div><div class="v v-red">'+idr(lots*perLot)+'</div></div>'
    +'<div class="metric"><div class="k">Exposure</div><div class="v v-muted">'+fmt(cap?val/cap*100:0,1)+'%</div></div>'
    +'</div>';
};

/* ---------- Portfolio risk & correlation ---------- */
$("#pfRiskRun").onclick = runPortfolioRisk;
async function runPortfolioRisk(){
  if(!positions.length){ $("#pfRisk").innerHTML='<div class="empty" style="padding:20px">Belum ada posisi.</div>'; return; }
  const cap=parseFloat($("#rkCapital").value)||100000000;
  showStatus("Menghitung risiko portofolio...", true);
  try{
    const d=await (await fetch('/api/portfolio-risk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({positions:positions,capital:cap})})).json();
    const rows=(d.rows||[]).map(x=>'<tr><td style="text-align:left;font-weight:700">'+x.ticker+'</td><td>'+idr(x.value)+'</td><td>'+x.weight_pct+'%</td><td class="'+(x.pl>=0?'v-up':'v-red')+'">'+(x.pl>=0?'+':'')+idr(x.pl)+'</td></tr>').join("");
    let html='<div class="grid">'
      +'<div class="metric hl"><div class="k">Exposure</div><div class="v v-white">'+d.exposure_pct+'%</div></div>'
      +'<div class="metric"><div class="k">Nilai Posisi</div><div class="v v-muted">'+idr(d.total_value)+'</div></div>'
      +'<div class="metric"><div class="k">Cash</div><div class="v v-up">'+d.cash_pct+'%</div></div></div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Kode</th><th>Nilai</th><th>Bobot</th><th>P/L</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
    if(d.sectors && d.sectors.length){
      html += '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Konsentrasi sektor</div>'
        + '<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Sektor</th><th>Nilai</th><th>Bobot</th></tr></thead><tbody>'
        + d.sectors.map(s=>'<tr><td style="text-align:left">'+s.sector+'</td><td>'+idr(s.value)+'</td><td>'+s.weight_pct+'%</td></tr>').join('')
        + '</tbody></table></div>';
    }
    if(d.flags && d.flags.length){
      html += '<div class="mono" style="color:#dc2626;font-size:11px;margin-top:12px;line-height:1.7">⚠ Batas risiko: ' + d.flags.join(' &middot; ') + '</div>';
    }
    const tks=[...new Set(positions.map(p=>p.ticker))];
    if(tks.length>=2){
      const cd=await (await fetch('/api/correlation?tickers=' + tks.join(','))).json();
      if(!cd.error){
        const hdr='<tr><th></th>'+cd.tickers.map(t=>'<th>'+t+'</th>').join('')+'</tr>';
        const body=cd.matrix.map((row,i)=>'<tr><td style="text-align:left;font-weight:700">'+cd.tickers[i]+'</td>'+row.map(v=>'<td style="color:'+(v>=0.7?'#ef5350':(v<=0.3?'#26a69a':'#a3a3a3'))+'">'+v+'</td>').join('')+'</tr>').join("");
        html+='<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Korelasi 120D (&ge;0.7 merah = terlalu mirip)</div><div style="overflow-x:auto"><table>'+hdr+body+'</table></div>';
      } else { html+='<div class="mono" style="color:#737373;font-size:11px;margin-top:12px">Korelasi: '+cd.error+'</div>'; }
    }
    $("#pfRisk").innerHTML=html; showStatus("Selesai");
  }catch(e){ $("#pfRisk").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
}

/* ---------- Trade journal ---------- */
let journal = LS.get("sbl_journal", []);
function renderJournal(){
  const el=$("#jrList");
  if(!journal.length){ el.innerHTML='<div class="empty" style="padding:24px">Belum ada catatan.</div>'; return; }
  el.innerHTML='<div style="overflow-x:auto"><table><thead><tr><th>Waktu</th><th style="text-align:left">Kode</th><th style="text-align:left">Catatan</th><th>Hasil</th><th></th></tr></thead><tbody>'
    +journal.map((j,i)=>'<tr><td>'+j.time+'</td><td style="text-align:left;font-weight:700;cursor:pointer" onclick="pick(\''+j.ticker+'\')">'+j.ticker+'</td><td style="text-align:left;color:#a3a3a3">'+j.note+'</td><td class="'+(j.result>=0?'v-up':'v-red')+'">'+(j.result!=null?(j.result>=0?'+':'')+j.result+'%':'-')+'</td><td><button class="btn ghost" style="padding:3px 8px" onclick="jrRemove('+i+')">x</button></td></tr>').join('')
    +'</tbody></table></div>';
}
function jrRemove(i){ journal.splice(i,1); LS.set("sbl_journal",journal); renderJournal(); }
$("#jrAdd").onclick=()=>{
  const t=($("#jrTicker").value||"").trim().toUpperCase();
  if(!t) return;
  const note=$("#jrNote").value||"-"; const resv=$("#jrResult").value;
  journal.unshift({time:new Date().toLocaleString("id-ID"),ticker:t,note:note,result: resv===""?null:parseFloat(resv)});
  LS.set("sbl_journal",journal); renderJournal();
  $("#jrTicker").value=""; $("#jrNote").value=""; $("#jrResult").value="";
};

/* ---------- Auto-scan + external notify ---------- */
let autoScanTimer=null;
let asSnapshot=LS.get("sbl_autoscan_snap",{});
function setAsStatus(txt){ const el=$("#asStatus"); if(el) el.textContent=txt; }
function renderAsResult(rows){
  const top=(rows||[]).filter(x=>x.Signal==="STRONG BUY"||x.Signal==="BUY").slice(0,20);
  $("#asResult").innerHTML = top.length ? '<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Kode</th><th>Skor</th><th>Sinyal</th><th>Aksi</th></tr></thead><tbody>'
    + top.map(x=>'<tr onclick="pick(\''+x.Ticker+'\')" style="cursor:pointer"><td style="text-align:left;font-weight:700">'+x.Ticker+'</td><td>'+x.Score+'</td><td><span class="tag s-'+signalClass(x.Signal)+'">'+x.Signal+'</span></td><td style="color:#a3a3a3">'+x.Action+'</td></tr>').join('')
    + '</tbody></table></div>' : '<div class="empty" style="padding:18px">Tidak ada sinyal beli di watchlist.</div>';
}
async function asScan(){
  const list=watchlist.join(",");
  if(!list){ showStatus("Watchlist kosong"); return; }
  setAsStatus("Scanning...");
  try{
    const d=await fetchJSON('/api/screen?list=' + encodeURIComponent(list) + '&top=50', {retries:2});
    if(d.error) throw new Error(d.error);
    const rows=d.rows||[]; const fresh=[];
    rows.forEach(x=>{ const prev=asSnapshot[x.Ticker]; const buy=x.Signal==="STRONG BUY"||x.Signal==="BUY";
      if(buy && prev!==x.Signal) fresh.push(x); asSnapshot[x.Ticker]=x.Signal; });
    LS.set("sbl_autoscan_snap",asSnapshot);
    renderAsResult(rows);
    setAsStatus("Scan terakhir "+new Date().toLocaleTimeString("id-ID")+" | "+rows.length+" saham"+(fresh.length?(" | "+fresh.length+" sinyal baru"):""));
    fresh.forEach(x=>fireAlertText(x.Ticker+" "+x.Signal+" (skor "+x.Score+")"));
  }catch(e){ setAsStatus("Scan gagal: "+e.message); }
}
function fireAlertText(text){
  showStatus("ALERT: "+text, false);
  if(window.Notification && Notification.permission==="granted"){ try{ new Notification("IDX Alert",{body:text}); }catch(e){} }
  fetch('/api/notify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text})}).catch(()=>{});
}
$("#asRun").onclick=asScan;
$("#asToggle").onclick=()=>{
  if(autoScanTimer){ clearInterval(autoScanTimer); autoScanTimer=null; $("#asToggle").textContent="Mulai Auto"; setAsStatus("Auto-scan OFF."); }
  else{
    const mins=parseInt($("#asInterval").value||"15");
    asScan();
    autoScanTimer=setInterval(asScan, mins*60000);
    $("#asToggle").textContent="Stop Auto";
    setAsStatus("Auto-scan ON tiap "+mins+" menit.");
  }
};

/* ---------- Theme + compare + model/news + optimizer + paper ---------- */
function applyTheme(t){
  document.documentElement.dataset.theme = t;
  try{ localStorage.setItem("sbl_theme", t); }catch(e){}
}
function remountCharts(){
  if(charts.analysis) loadChart("analysis","#liveChart",charts.analysis.ticker,charts.analysis.interval,false);
  if(charts.live) loadChart("live","#tv_chart",charts.live.ticker,charts.live.interval,false);
}
$("#themeBtn").onclick = () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  remountCharts();
};
$("#cmp").onchange = (e) => {
  showBench = e.target.checked;
  Object.keys(charts).forEach((k) => { const api = charts[k]; if(api && api.series && api.series.bench) api.series.bench.setData(showBench ? (api.benchmark||[]) : []); });
};

async function loadMl(t){
  const el = document.getElementById("mlCard"); if(!el) return;
  el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">11</span><div class="line"></div><span class="badge">Model ML (logistic)</span></div><div class="empty">Melatih model...</div></div>';
  try{
    const m = await (await fetch('/api/ml?ticker=' + encodeURIComponent(t) + '&horizon=10')).json();
    if(m.error) throw new Error(m.error);
    const pct = (v) => v==null?"-":(Number(v)*100).toFixed(1)+"%";
    const prob = m.current_prob_up;
    const cls = prob>=0.6?"v-up":(prob<=0.4?"v-red":"v-muted");
    const wrows = (m.weights||[]).slice(0,8).map((w,i)=>'<div class="check" style="justify-content:space-between"><span>'+(i+1)+'. '+w.factor+'</span><span class="mono '+(w.weight>=0?'v-up':'v-red')+'">'+(w.weight>=0?'+':'')+w.weight+'</span></div>').join("");
    el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">11</span><div class="line"></div><span class="badge">Model ML (logistic)</span></div>'
      + '<div class="grid">'
      + '<div class="metric hl"><div class="k">Probabilitas Naik</div><div class="v '+cls+'">'+pct(prob)+'</div></div>'
      + '<div class="metric"><div class="k">Akurasi (out-of-sample)</div><div class="v v-white">'+pct(m.test_accuracy)+'</div></div>'
      + '<div class="metric"><div class="k">Base Rate</div><div class="v v-muted">'+pct(m.base_rate)+'</div></div>'
      + '<div class="metric"><div class="k">Edge vs Base</div><div class="v '+(m.edge_vs_base>=0?'v-up':'v-red')+'">'+(m.edge_vs_base==null?'-':(m.edge_vs_base>=0?'+':'')+pct(m.edge_vs_base))+'</div></div>'
      + '<div class="metric"><div class="k">Sampel / Train / Test</div><div class="v v-muted">'+m.samples+' / '+m.train+' / '+m.test+'</div></div>'
      + '</div>'
      + '<div class="mono" style="color:#7c8c83;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 6px">Bobot faktor (kontribusi)</div>'
      + '<div class="checks" style="grid-template-columns:1fr">'+wrows+'</div>'
      + '<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:10px">Heuristik statistik (bukan jaminan). Probabilitas = peluang historis naik dalam 10 bar.</div>'
      + '</div>';
  }catch(e){ el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">11</span><div class="line"></div><span class="badge">Model ML</span></div><div class="empty">Gagal: '+e.message+'</div></div>'; }
}

async function loadNews(t){
  const el = document.getElementById("newsCard"); if(!el) return;
  el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">12</span><div class="line"></div><span class="badge">Sentimen Berita</span></div><div class="empty">Memuat berita...</div></div>';
  try{
    const n = await (await fetch('/api/news?ticker=' + encodeURIComponent(t))).json();
    if(n.error) throw new Error(n.error);
    const cls = n.label==="Positif"?"v-up":(n.label==="Negatif"?"v-red":"v-muted");
    const items = (n.items||[]).slice(0,8).map(it=>{
      const s = it.sentiment>=0.2?"v-up":(it.sentiment<=-0.2?"v-red":"v-muted");
      const link = it.url ? '<a href="'+it.url+'" target="_blank" rel="noreferrer" style="color:var(--brand-dark);text-decoration:none">'+(it.title||"-")+'</a>' : (it.title||"-");
      return '<div class="check" style="align-items:flex-start"><span class="ic '+s+'">'+(it.sentiment>0?'▲':(it.sentiment<0?'▼':'•'))+'</span><span style="flex:1">'+link+'<br><span class="mono" style="color:#8a9a90;font-size:10px">'+(it.publisher||"")+'</span></span></div>';
    }).join("");
    el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">12</span><div class="line"></div><span class="badge">Sentimen Berita</span></div>'
      + '<div class="grid"><div class="metric hl"><div class="k">Sentimen</div><div class="v '+cls+'">'+n.label+'</div></div>'
      + '<div class="metric"><div class="k">Skor rata-rata</div><div class="v v-muted">'+n.avg_sentiment+'</div></div>'
      + '<div class="metric"><div class="k">Jumlah berita</div><div class="v v-white">'+n.count+'</div></div></div>'
      + (items ? '<div style="margin-top:12px">'+items+'</div>' : '<div class="empty" style="padding:20px">Tidak ada berita.</div>')
      + '</div>';
  }catch(e){ el.innerHTML = '<div class="card glass modish"><div class="sec"><span class="num">12</span><div class="line"></div><span class="badge">Sentimen Berita</span></div><div class="empty">Gagal: '+e.message+'</div></div>'; }
}

$("#optRun").onclick = runOptimize;
async function runOptimize(){
  const t=($("#btTicker").value||"").trim().toUpperCase(); if(!t) return;
  showStatus("Mengoptimalkan parameter...", true); $("#optRun").disabled=true;
  try{
    const d=await (await fetch('/api/optimize?ticker=' + encodeURIComponent(t))).json();
    if(d.error) throw new Error(d.error);
    const pct=(v)=> v==null?"-":(Number(v)*100).toFixed(1)+"%";
    const rows=(d.top||[]).map((x,i)=>'<tr><td>'+(i+1)+'</td><td>'+x.min_score+'</td><td>'+x.tp_rr+'</td><td>'+x.sl_mult+'</td>'
      +'<td class="'+(x.total_return>=0?'v-up':'v-red')+'">'+pct(x.total_return)+'</td>'
      +'<td>'+(x.profit_factor==null?'~':Number(x.profit_factor).toFixed(2))+'</td>'
      +'<td>'+x.n_trades+'</td><td>'+pct(x.win_rate)+'</td></tr>').join("");
    const b=d.best;
    $("#optResult").innerHTML = '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px">Optimizer ('+d.tested+' kombinasi)</div>'
      + (b ? '<div class="mono" style="color:#33443b;font-size:12px;margin-bottom:8px">Terbaik: min_skor '+b.min_score+' · TP RR '+b.tp_rr+' · SL x ATR '+b.sl_mult+'</div>' : '')
      + '<div style="overflow-x:auto"><table><thead><tr><th>#</th><th>MinSkor</th><th>TP RR</th><th>SL ATR</th><th>Return</th><th>PF</th><th>Trade</th><th>Win</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
      + '<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:10px">Hati-hati overfitting: validasi dengan Walk-forward.</div>';
    showStatus("Selesai");
  }catch(e){ $("#optResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ $("#optRun").disabled=false; }
}

$("#ppOpen").onclick = async () => {
  const ticker=($("#ppTicker").value||"").trim().toUpperCase();
  const entry=parseFloat($("#ppEntry").value||"0")||null;
  const lots=parseInt($("#ppLots").value||"0")||0;
  if(!ticker||!lots){ showStatus("Isi kode & lot"); return; }
  try{
    await fetch('/api/paper/open',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ticker:ticker,entry:entry,lots:lots,stop:parseFloat($("#ppStop").value)||0,tp:parseFloat($("#ppTp").value)||0})});
    $("#ppTicker").value=""; $("#ppEntry").value=""; $("#ppStop").value=""; $("#ppTp").value="";
    loadPaper();
  }catch(e){ showStatus("Gagal buka posisi"); }
};
$("#ppRefresh").onclick = loadPaper;
async function loadPaper(){
  const el=$("#ppList"); if(!el) return;
  el.innerHTML='<div class="empty" style="padding:20px">Memuat...</div>';
  try{
    const d=await (await fetch('/api/paper')).json();
    const rows=(d.rows||[]);
    if(!rows.length){ el.innerHTML='<div class="empty" style="padding:20px">Belum ada posisi paper.</div>'; return; }
    el.innerHTML='<div style="overflow-x:auto"><table><thead><tr><th>Kode</th><th>Entry</th><th>Lot</th><th>Harga</th><th>P/L</th><th>Status</th><th></th></tr></thead><tbody>'
      + rows.map(r=>{
          const pnl = r.pnl; const cls = pnl==null?"":(pnl>=0?"v-up":"v-red");
          return '<tr><td style="font-weight:700;cursor:pointer" onclick="pick(\''+r.ticker+'\')">'+r.ticker+'</td>'
            +'<td>'+fmt(r.entry)+'</td><td>'+r.lots+'</td><td>'+(r.last!=null?idr(r.last):"-")+'</td>'
            +'<td class="'+cls+'">'+(pnl!=null?(pnl>=0?'+':'')+idr(pnl)+(r.pnl_pct!=null?' ('+(r.pnl_pct>=0?'+':'')+fmt(r.pnl_pct,2)+'%)':''):'-')+'</td>'
            +'<td>'+(r.status==='OPEN'?'<span class="tag s-BUY">OPEN</span>':(r.pnl>=0?'<span class="tag s-BUY">CLOSED +</span>':'<span class="tag s-SELL">CLOSED -</span>'))+'</td>'
            +'<td>'+(r.status==='OPEN'?'<button class="btn ghost" style="padding:3px 8px" onclick="ppClose('+r.id+')">Tutup</button>':'')+'</td></tr>';
        }).join('')+'</tbody></table></div>';
  }catch(e){ el.innerHTML='<div class="empty">Gagal memuat.</div>'; }
}
async function ppClose(id){
  try{ await fetch('/api/paper/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})}); loadPaper(); }
  catch(e){ showStatus("Gagal tutup"); }
}

$("#dbRefresh").onclick = loadDb;
async function loadDb(){
  const el=$("#dbList"); if(!el) return;
  el.innerHTML='<div class="empty" style="padding:20px">Memuat...</div>';
  try{
    const [sg, sc] = await Promise.all([fetch('/api/db/signals?limit=20').then(r=>r.json()), fetch('/api/db/scans').then(r=>r.json())]);
    const srows=(sg.rows||[]).map(x=>'<tr><td>'+x.ts.slice(5,16)+'</td><td style="text-align:left;font-weight:700;cursor:pointer" onclick="pick(\''+x.ticker+'\')">'+x.ticker+'</td><td><span class="tag s-'+signalClass(x.signal)+'">'+x.signal+'</span></td><td>'+x.score+'</td><td>'+x.source+'</td></tr>').join("");
    const crows=(sc.rows||[]).map(x=>'<tr><td>'+x.ts.slice(5,16)+'</td><td style="text-align:left">'+x.universe+'</td><td>'+x.n+'</td><td>'+x.buys+'</td></tr>').join("");
    el.innerHTML = '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">Sinyal tersimpan</div>'
      + (srows?'<div style="overflow-x:auto"><table><thead><tr><th>Waktu</th><th>Kode</th><th>Sinyal</th><th>Skor</th><th>Sumber</th></tr></thead><tbody>'+srows+'</tbody></table></div>':'<div class="empty" style="padding:14px">Kosong. Jalankan scheduler.py atau analisis manual.</div>')
      + '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 6px">Log scan otomatis</div>'
      + (crows?'<div style="overflow-x:auto"><table><thead><tr><th>Waktu</th><th>Universe</th><th>Discan</th><th>Beli</th></tr></thead><tbody>'+crows+'</tbody></table></div>':'<div class="empty" style="padding:14px">Belum ada scan otomatis (jalankan <b>py scheduler.py</b>).</div>');
  }catch(e){ el.innerHTML='<div class="empty">Gagal memuat.</div>'; }
}

/* ---------- Musyawarah (multi-agent consensus) ---------- */
$("#myRun").onclick = runMusyawarah;
async function runMusyawarah(){
  const t=($("#myTicker").value||"").trim().toUpperCase(); if(!t) return;
  const useLlm = $("#myLlm") && $("#myLlm").checked;
  showStatus("Musyawarah 5 agen...", true); $("#myRun").disabled=true;
  try{
    const d=await (await fetch('/api/musyawarah?ticker='+encodeURIComponent(t)+(useLlm?'&llm=1':''))).json();
    if(d.error) throw new Error(d.error);
    const cls = d.decision==="BUY"?"v-up":(d.decision==="SKIP"?"v-red":"v-muted");
    const p=d.perspectives||{};
    const bstat=(p.bandarmologi||{}).status||"-";
    const v=d.votes||{};
    const vrow=(label,val)=>'<div class="check" style="justify-content:space-between"><span>'+label+'</span><span class="mono '+(val>0?'v-up':(val<0?'v-red':'v-muted'))+'">'+(val>0?'+':'')+Number(val).toFixed(2)+'</span></div>';
    window.__myText = d.text;
    $("#myResult").innerHTML =
      '<div class="grid">'
      +'<div class="metric hl"><div class="k">Keputusan</div><div class="v '+cls+'">'+d.decision+'</div></div>'
      +'<div class="metric"><div class="k">Conviction</div><div class="v v-white">'+d.conviction+'%</div></div>'
      +'<div class="metric"><div class="k">Konsensus</div><div class="v '+(d.consensus>0?'v-up':(d.consensus<0?'v-red':'v-muted'))+'">'+(d.consensus>0?'+':'')+d.consensus+'</div></div>'
      +'<div class="metric"><div class="k">Prob. ML</div><div class="v v-muted">'+(d.ml_prob_up!=null?(d.ml_prob_up*100).toFixed(1)+'%':'-')+'</div></div>'
      +'<div class="metric"><div class="k">Risk/Reward</div><div class="v v-muted">1:'+d.rr+'</div></div>'
      +'<div class="metric"><div class="k">Bandarmologi</div><div class="v '+(bstat==='DISTRIBUSI MASIF'?'v-red':'v-muted')+'">'+bstat+'</div></div>'
      +'<div class="metric"><div class="k">Entry</div><div class="v v-white">'+idr(d.entry)+'</div></div>'
      +'<div class="metric"><div class="k">Target</div><div class="v v-up">'+idr(d.target)+'</div></div>'
      +'</div>'
      + '<div class="mono" style="color:#7c8c83;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 4px">Voting agen (bobot 40/30/15/15)</div>'
      + '<div class="checks" style="grid-template-columns:1fr 1fr">'+vrow('@technical',v.technical||0)+vrow('@bandarmologi',v.bandarmologi||0)+vrow('@fundamental',v.fundamental||0)+vrow('@sentiment',v.sentiment||0)+'</div>'
      + '<div class="mono" style="background:var(--surface);border:1px solid var(--border);color:var(--foreground);border-radius:12px;padding:16px;margin-top:16px;white-space:pre-wrap;font-size:12px;line-height:1.7;overflow-x:auto">'+String(d.text).replace(/</g,"&lt;")+'</div>'
      + '<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:8px">Engine: '+d.engine+'</div>';
    showStatus("Selesai");
  }catch(e){ $("#myResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ $("#myRun").disabled=false; }
}
$("#myCopy").onclick = () => {
  if(!window.__myText){ showStatus("Belum ada hasil"); return; }
  if(navigator.clipboard){ navigator.clipboard.writeText(window.__myText).then(()=>showStatus("Hasil dicopy"),()=>showStatus("Gagal copy")); }
  else showStatus("Clipboard tidak didukung");
};

/* ---------- Weight optimizer (consensus backtest) ---------- */
$("#myWeightsBtn").onclick = runOptimizeWeights;
async function runOptimizeWeights(){
  showStatus("Menguji bobot (backtest)...", true); $("#myWeightsBtn").disabled=true;
  try{
    const d=await (await fetch('/api/optimize-weights?list=idx30')).json();
    if(d.error) throw new Error(d.error);
    const rows=(d.leaderboard||[]).map((x,i)=>'<tr><td>'+(i+1)+'</td><td>'+x.w_technical+' / '+x.w_bandarmologi+'</td><td>'+x.threshold+'</td>'
      +'<td class="'+(x.mean_return>=0?'v-up':'v-red')+'">'+x.mean_return+'%</td><td>'+(x.mean_pf==null?'~':x.mean_pf)+'</td>'
      +'<td>'+(x.mean_win_rate*100).toFixed(0)+'%</td><td>'+x.trades+'</td></tr>').join("");
    $("#myWeights").innerHTML = '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px">Optimasi bobot technical:bandarmologi ('+d.tickers+' saham, '+d.tested+' kombinasi)</div>'
      + (d.best?'<div class="mono" style="color:#33443b;font-size:12px;margin-bottom:8px">Terbaik: technical '+d.best.w_technical+' : bandarmologi '+d.best.w_bandarmologi+' &middot; threshold '+d.best.threshold+' &middot; return rata-rata '+d.best.mean_return+'%</div>':'')
      + '<div style="overflow-x:auto"><table><thead><tr><th>#</th><th>Tech:Bandar</th><th>Thr</th><th>Return</th><th>PF</th><th>Win</th><th>Trade</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
      + '<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:10px">'+d.note+'</div>';
    showStatus("Selesai");
  }catch(e){ $("#myWeights").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ $("#myWeightsBtn").disabled=false; }
}

/* ---------- Data quality ---------- */
$("#dqRun").onclick = runDataQuality;
async function runDataQuality(){
  const list=($("#mkList") && $("#mkList").value)||"lq45";
  showStatus("Memeriksa kualitas data...", true); $("#dqRun").disabled=true;
  try{
    const d=await (await fetch('/api/data/quality?list='+encodeURIComponent(list))).json();
    if(d.error) throw new Error(d.error);
    const rows=(d.items||[]).map(x=>'<tr><td style="text-align:left;font-weight:700">'+x.ticker+'</td>'
      +'<td>'+(x.rows||0)+'</td><td>'+(x.last||'-')+'</td>'
      +'<td class="'+(x.ok?'v-up':'v-red')+'">'+(x.ok?'OK':'ISSUE')+'</td>'
      +'<td style="text-align:left;color:#7c8c83">'+(((x.issues||[]).join('; '))||'-')+'</td></tr>').join("");
    $("#dqResult").innerHTML='<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">Kualitas data: '+(d.ok)+'/'+(d.total)+' OK</div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Kode</th><th>Bar</th><th>Terakhir</th><th>Status</th><th style="text-align:left">Catatan</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
    showStatus("Selesai");
  }catch(e){ $("#dqResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ $("#dqRun").disabled=false; }
}

/* ===================== UI/UX v2 ===================== */
function enhanceTables(){
  document.querySelectorAll("table:not(.as-cards)").forEach(function(tbl){
    var heads = Array.prototype.map.call(tbl.querySelectorAll("thead th"), function(th){ return th.textContent.trim(); });
    if(!heads.length) return;
    tbl.querySelectorAll("tbody tr").forEach(function(tr){
      Array.prototype.forEach.call(tr.children, function(td,i){
        if(heads[i] && !td.getAttribute("data-label")) td.setAttribute("data-label", heads[i]);
      });
    });
    tbl.classList.add("as-cards");
  });
}
var _tblTimer=null;
function scheduleEnhance(){ clearTimeout(_tblTimer); _tblTimer=setTimeout(enhanceTables, 80); }
new MutationObserver(scheduleEnhance).observe(document.body,{childList:true,subtree:true});

async function loadSummary(){
  var el=document.getElementById("summaryBar"); if(!el) return;
  try{
    var d=await (await fetch("/api/summary")).json();
    var ih=d.ihsg||{}; var up=(Number(ih.ret_1d)||0)>=0;
    var sc=(d.scans&&d.scans[0])||null;
    var wl=(typeof watchlist!=="undefined" && watchlist)?watchlist.length:0;
    el.innerHTML =
      '<div class="s-card brand"><div class="k">IHSG</div><div class="v">'+fmt(ih.price)+'</div><div class="sub '+(up?'v-up':'v-red')+'">'+(up?'+':'-')+Math.abs(Number(ih.ret_1d)||0).toFixed(2)+'% · '+(ih.regime||'-')+'</div></div>'
      + '<div class="s-card"><div class="k">Sinyal Beli Hari Ini</div><div class="v v-up">'+(d.signals_today||0)+'</div><div class="sub">dari riwayat scanner</div></div>'
      + '<div class="s-card"><div class="k">Scan Terakhir</div><div class="v">'+(sc?sc.n:'-')+'</div><div class="sub">'+(sc?((sc.universe||"").toUpperCase()+' · '+sc.buys+' beli'):'belum ada')+'</div></div>'
      + '<div class="s-card"><div class="k">Watchlist</div><div class="v">'+wl+'</div><div class="sub">saham dipantau</div></div>';
  }catch(e){ el.innerHTML=''; }
}

function showOnboard(){ var el=document.getElementById("onboard"); if(el) el.classList.add("show"); }
function hideOnboard(){ var el=document.getElementById("onboard"); if(el) el.classList.remove("show"); try{ localStorage.setItem("sbl_onboarded","1"); }catch(e){} }
(function(){
  var b=document.getElementById("onboardClose"); if(b) b.onclick=hideOnboard;
  var h=document.getElementById("helpBtn"); if(h) h.onclick=showOnboard;
  var o=document.getElementById("onboard"); if(o) o.addEventListener("click",function(e){ if(e.target.id==="onboard") hideOnboard(); });
  var seen=false; try{ seen=!!localStorage.getItem("sbl_onboarded"); }catch(e){ seen=true; }
  if(!seen) setTimeout(showOnboard, 700);
})();

var TAB_ORDER=["analisis","screener","live","backtest","portofolio","akurasi","pasar","musyawarah"];
document.addEventListener("keydown",function(e){
  var tag=(e.target.tagName||"").toLowerCase();
  if(tag==="input"||tag==="select"||tag==="textarea") return;
  if(e.key>="1"&&e.key<="8"){ var t=document.querySelector('.tab[data-tab="'+TAB_ORDER[Number(e.key)-1]+'"]'); if(t) t.click(); }
  else if(e.key==="/"){ e.preventDefault(); var inp=document.getElementById("ticker"); if(inp){ inp.focus(); if(inp.select) inp.select(); } }
  else if(e.key==="?"){ showOnboard(); }
  else if(e.key==="t"||e.key==="T"){ var tb=document.getElementById("themeBtn"); if(tb) tb.click(); }
});

(function init(){
  try{ applyTheme(localStorage.getItem("sbl_theme") || "light"); }catch(e){}
  if("serviceWorker" in navigator){ navigator.serviceWorker.register("/static/sw.js", {updateViaCache:"none"}).then(r=>r.update()).catch(()=>{}); }
  const yr = document.getElementById("yr"); if(yr) yr.textContent = new Date().getFullYear();
  const q = new URLSearchParams(location.search);
  if(q.get("ticker")) $("#ticker").value = q.get("ticker").toUpperCase();
  if(q.get("interval")) $("#interval").value = q.get("interval");
  const tab = q.get("tab");
  if(tab){
    const el = document.querySelector(`.tab[data-tab="${tab}"]`);
    if(el) el.click();
  }
  fetch("/api/sectors").then(r=>r.json()).then(d=>{
    const sel = $("#scSector");
    if(!sel) return;
    const seen = {};
    Object.values(d.sectors||{}).forEach(s=>{ seen[s]=1; });
    Object.keys(seen).sort().forEach(s=>{ const o=document.createElement("option"); o.value=s; o.textContent=s; sel.appendChild(o); });
  }).catch(()=>{});
  const sc=$("#scList"), mk=$("#mkList");
  if(sc && mk){ Array.from(sc.options).forEach(o=>{ if(o.value && o.value!=="custom"){ const opt=document.createElement("option"); opt.value=o.value; opt.textContent=o.textContent; mk.appendChild(opt); } }); }
  renderJournal();
  enhanceTables();
  loadSummary();
  fetch("/api/llm/status").then(r=>r.json()).then(s=>{ const el=$("#myLlmStatus"); if(el) el.textContent = "Mode LLM: " + (s.configured ? ("siap (" + s.model + ")") : "belum dikonfigurasi (set OPENAI_API_KEY / LLM_API_KEY)") + " | prompt MD: " + (s.prompt ? "ditemukan" : "default"); }).catch(()=>{});
  renderWatchlist(); renderPositions(); renderAlerts(); loadHistory(); pollPortfolio();
  loadPaper(); loadDb();
  setInterval(pollPortfolio, 20000);
})();
analyze();
