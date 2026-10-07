document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  const name = t.dataset.tab;
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active", x.dataset.tab===name));
  document.querySelectorAll(".panel").forEach(x=>x.classList.remove("active"));
  const panel = $("#panel-"+name); if(panel) panel.classList.add("active");
  if(name==="live") loadLiveChart();
  if(name==="portofolio") refreshPortfolio();
  if(name==="fundamental"){ syncFuInputs(); loadFundamentalTab(); }
  if(name==="berita"){ syncFuInputs(); loadNewsTab(); }
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
        <div class="meta">${d.trend} &middot; W:${d.weekly_trend} &middot; ${d.regime} &middot; Pasar:${d.market_regime||'-'} &middot; ${d.last_date} &middot; ${d.bars} bar${d.model_used?' &middot; <b>SKOR OPT</b>':''}
          <span id="liveStamp" class="mono" style="color:#525252">${d.live?("· LIVE "+(d.quote_source||"")):""}</span></div>
      </div>
      <div style="text-align:center;min-width:150px">
        <div class="mono" style="font-size:9px;color:#525252;letter-spacing:.16em">CONFIDENCE</div>
        <div class="grade" style="color:${cc};margin-top:2px">${d.grade}</div>
        <div class="mono" style="font-size:20px;font-weight:900;margin-top:2px">${d.confidence}%</div>
        <div class="mono" style="font-size:9px;color:#525252;margin-top:4px">${passed}/${d.checklist.length} faktor</div>
        ${(d.model_used && d.prob_up!=null)?`<div class="mono" style="font-size:10px;color:#525252;margin-top:3px">Prob ML ${fmt(d.prob_up*100,0)}%${d.score_opt!=null?' · opt '+fmt(d.score_opt,0):''}</div>`:''}
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

    <div class="card glass modish">
      <div class="sec"><span class="num">03C</span><div class="line"></div><span class="badge">Indikator Mutakhir</span></div>
      <div class="grid">
        <div class="metric"><div class="k">Hull MA 20</div><div class="v ${d.price>=d.hma20?'v-up':'v-red'}">${idr(d.hma20)}</div></div>
        <div class="metric"><div class="k">KAMA</div><div class="v ${d.price>=d.kama?'v-up':'v-red'}">${idr(d.kama)}</div></div>
        <div class="metric"><div class="k">Aroon Up / Down</div><div class="v ${d.aroon_up>=d.aroon_down?'v-up':'v-red'}">${fmt(d.aroon_up,0)} / ${fmt(d.aroon_down,0)}</div></div>
        <div class="metric"><div class="k">Vortex + / -</div><div class="v ${d.vortex_plus>=d.vortex_minus?'v-up':'v-red'}">${fmt(d.vortex_plus,2)} / ${fmt(d.vortex_minus,2)}</div></div>
        <div class="metric"><div class="k">Awesome Osc</div><div class="v ${d.ao>=0?'v-up':'v-red'}">${fmt(d.ao,1)}</div></div>
        <div class="metric"><div class="k">Ultimate Osc</div><div class="v ${d.uo>=50?'v-up':'v-red'}">${fmt(d.uo,1)}</div></div>
        <div class="metric"><div class="k">RVOL</div><div class="v ${d.rvol>=1.2?'v-up':'v-muted'}">${fmt(d.rvol,2)}x</div></div>
      </div>
      <div class="mono" style="margin-top:10px;color:#8a9a90;font-size:10px">Kandidat faktor baru — divalidasi di tab Akurasi sebelum masuk skor.</div>
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
  if($("#scBg") && $("#scBg").checked){ return runScreenBackground(list); }
  _scCancel = false;
  $("#scRun").disabled = true;
  const minS=$("#scMin").value, minC=$("#scConf").value, sec=$("#scSector").value,
        mv=$("#scValue").value||0, bull=$("#scBull").checked?1:0, rfr=$("#scRefresh").checked?1:0;
  try{
    showStatus("Menyiapkan daftar saham...", true);
    const tinfo = await fetchJSON(`/api/tickers?list=${encodeURIComponent(list)}`);
    const tickers = (tinfo && tinfo.tickers) || [];
    if(!tickers.length){ $("#scResult").innerHTML='<div class="empty">Daftar saham kosong.</div>'; return; }
    showStatus("Memindai " + tickers.length + " saham... (batch 1 sedang diunduh)", true);
    const chunkSize = 60, CONC = 3;
    const chunks = [];
    for(let i=0;i<tickers.length;i+=chunkSize) chunks.push(tickers.slice(i, i+chunkSize));
    let merged = [], scanned = 0;
    const finalRows = () => {
      let m = merged;
      if($("#scSqz").checked) m = m.filter(x => x.Sqz==="OFF" && Number(x.SqzMom)>0);
      m = m.slice().sort((a,b)=> (b.Score-a.Score) || (b.Conf-a.Conf));
      const top = parseInt($("#scTop").value||"0",10);
      return (top>0) ? m.slice(0, top) : m;
    };
    const renderNow = throttle(()=>{ renderScanRows(finalRows(), tickers.length, scanned); }, 900);
    showScProgress(0, tickers.length, true);
    await mapLimit(chunks, CONC, async (chunk)=>{
      if(_scCancel) return;
      const url = `/api/screen?list=${encodeURIComponent(chunk.join(","))}&top=1000&min_score=${minS}&min_conf=${minC}&sector=${encodeURIComponent(sec)}&min_value=${mv}&only_bullish=${bull}&refresh=${rfr}`;
      try{ const d = await fetchJSON(url, {retries:2}); merged = merged.concat(d.rows||[]); }catch(e){}
      scanned += chunk.length;
      showScProgress(scanned, tickers.length, true);
      renderNow();
    });
    showScProgress(scanned, tickers.length, false);
    renderScanRows(finalRows(), tickers.length, scanned);
    showStatus(_scCancel ? "Dibatalkan" : "Selesai");
  }catch(e){
    $("#scResult").innerHTML = '<div class="empty">Gagal: '+e.message+'. Server mungkin sedang bangun — coba lagi.</div>';
    showStatus("Gagal");
  }
  finally{ $("#scRun").disabled=false; }
}
let _bgJob = null;
async function runScreenBackground(list){
  _scCancel = false;
  $("#scRun").disabled = true;
  const body = {
    list: list,
    min_score: $("#scMin").value, min_conf: $("#scConf").value,
    sector: $("#scSector").value, min_value: $("#scValue").value||0,
    only_bullish: $("#scBull").checked, refresh: $("#scRefresh").checked
  };
  try{
    showStatus("Menjalankan scan latar...", true);
    const s = await fetchJSON('/api/scan/start', {fetchOpts:{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)}});
    _bgJob = s.job;
    showScProgress(0, 1, true);
    await new Promise((resolve)=>{
      const tick = async ()=>{
        try{
          if(_scCancel){ try{ await fetchJSON('/api/scan/cancel', {fetchOpts:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:_bgJob})}}); }catch(e){} }
          const st = await fetchJSON('/api/scan/status?id='+encodeURIComponent(_bgJob));
          const total = st.total||0, done = st.scanned||0;
          showScProgress(done, total||1, !(st.state==="done"||st.state==="error"||st.state==="cancelled"));
          let m = st.rows||[];
          if($("#scSqz").checked) m = m.filter(x => x.Sqz==="OFF" && Number(x.SqzMom)>0);
          m = m.slice().sort((a,b)=> (b.Score-a.Score) || (b.Conf-a.Conf));
          const top = parseInt($("#scTop").value||"0",10);
          const rows = (top>0) ? m.slice(0, top) : m;
          if(total) renderScanRows(rows, total, done);
          if(st.state==="done"){ _bgJob=null; showScProgress(done,total,false); showStatus("Selesai"); resolve(); return; }
          if(st.state==="error"){ showStatus("Gagal: "+(st.error||"")); resolve(); return; }
          if(st.state==="cancelled"){ showStatus("Dibatalkan"); resolve(); return; }
          setTimeout(tick, 1500);
        }catch(e){ setTimeout(tick, 2500); }
      };
      tick();
    });
  }catch(e){
    $("#scResult").innerHTML = '<div class="empty">Gagal: '+e.message+'. Server mungkin sedang bangun — coba lagi.</div>';
    showStatus("Gagal");
  } finally { $("#scRun").disabled=false; }
}

function pick(t){
  $("#ticker").value = t;
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active", x.dataset.tab==="analisis"));
  document.querySelectorAll(".panel").forEach(x=>x.classList.remove("active"));
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

