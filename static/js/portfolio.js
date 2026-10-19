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
    + '<span style="cursor:pointer" data-action="pick" data-arg="' + escapeHtml(t) + '">' + escapeHtml(t) + '</span>'
    + '<span><span class="mono" id="wl-' + escapeHtml(t) + '" style="color:var(--muted)">' + (posQuotes[t]!=null?idr(posQuotes[t]):"-") + '</span>'
    + '<button class="btn ghost" style="padding:3px 8px;margin-left:8px" data-action="wlRemove" data-arg="' + escapeHtml(t) + '">x</button></span></div>').join("");
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
          + '<td style="font-weight:700;cursor:pointer" data-action="pick" data-arg="' + escapeHtml(p.ticker) + '">' + escapeHtml(p.ticker) + '</td>'
          + '<td>' + fmt(p.entry) + '</td><td>' + p.lots + '</td>'
          + '<td>' + (q!=null?idr(q):"-") + '</td>'
          + '<td class="' + cls + '">' + (pl!=null ? (pl>=0?'+':'')+idr(pl)+' ('+(plPct>=0?'+':'')+fmt(plPct,2)+'%)' : "-") + '</td>'
          + '<td style="color:#ef5350">' + (p.sl?fmt(p.sl):"-") + '</td>'
          + '<td style="color:#26a69a">' + (p.tp?fmt(p.tp):"-") + '</td>'
          + '<td><button class="btn ghost" style="padding:3px 8px" data-action="posRemove" data-idx="' + i + '">x</button></td></tr>';
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
      + '<span><span class="mono" style="color:var(--muted)">' + (q!=null?idr(q):"-") + '</span>'
      + '<button class="btn ghost" style="padding:3px 8px;margin-left:8px" data-action="alRemove" data-idx="' + i + '">x</button></span></div>';
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
      + '<td style="font-weight:700;cursor:pointer" data-action="pick" data-arg="' + escapeHtml(x.ticker) + '">' + escapeHtml(x.ticker) + '</td>'
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
  el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Fundamental</span></div><div class="empty">Memuat fundamental...</div></div>';
  try{
    const f = await (await fetch('/api/fundamental?ticker=' + encodeURIComponent(t))).json();
    if(f.error) throw new Error(f.error);
    const num=(v)=> v==null?"-":Number(v).toFixed(2);
    const pct=(v)=> v==null?"-":(Number(v)*100).toFixed(2)+"%";
    const dy=(v)=> v==null?"-":Number(v).toFixed(2)+"%";
    const capv=(v)=> v==null?"-":(Number(v)/1e12).toFixed(2)+" T";
    el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Fundamental</span></div><div class="grid">'
      + '<div class="metric"><div class="k">Nama</div><div class="v v-white" style="font-size:13px">' + escapeHtml(f.name || t) + '</div></div>'
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
  }catch(e){ el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Fundamental</span></div><div class="empty">Gagal memuat fundamental.</div></div>'; }
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
    $("#btWf").innerHTML = '<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px">Walk-forward (segmen out-of-sample)</div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th>Fold</th><th>Mulai</th><th>Selesai</th><th>Trade</th><th>Return</th><th>B&amp;H</th><th>Win</th><th>MaxDD</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
    showStatus("Selesai");
  }catch(e){ $("#btWf").innerHTML='<div class="empty">Gagal: '+escapeHtml(e.message)+'</div>'; showStatus("Gagal"); }
}

/* ---------- Market dashboard ---------- */
$("#mkRun").onclick = runMarket;
async function runMarket(){
  const list=$("#mkList").value; if(!list) return;
  showStatus("Mengambil data pasar...", true); $("#mkRun").disabled=true;
  try{
    const pair = await Promise.all([
      fetch('/api/market?list=' + encodeURIComponent(list)).then(function(r){ return r.json(); }),
      fetch('/api/external').then(function(r){ return r.json(); }).catch(function(){ return null; })
    ]);
    const d = pair[0];
    const ext = pair[1];
    if(d.error) throw new Error(d.error);
    const pct=(v)=> v==null?"-":(Number(v)).toFixed(2)+"%";
    const ih=d.ihsg||{}; const br=d.breadth||{};
    const secs=d.sectors||[];
    const colMax=(key)=>{ let m=0; secs.forEach(s=>{ const n=Number(s[key]); if(isFinite(n)) m=Math.max(m,Math.abs(n)); }); return m; };
    const mx1d=colMax('chg_1d'), mx5d=colMax('chg_5d'), mx20d=colMax('chg_20d');
    const heatCls=(v,max)=>{ const n=Number(v); if(v==null||!isFinite(n)) return ''; let c=(n>=0?'v-up':'v-red'); if(isFinite(max)&&max>0){ const lvl=Math.min(5,Math.max(1,Math.ceil(Math.abs(n)/max*5))); c+=' heat-cell '+(n>=0?'heat-pos-':'heat-neg-')+lvl; } return c; };
    const heat=secs.map(s=>'<tr><td style="text-align:left">'+escapeHtml(s.sector)+'</td><td>'+s.n+'</td>'
      +'<td class="'+heatCls(s.chg_1d,mx1d)+'">'+pct(s.chg_1d)+'</td>'
      +'<td class="'+heatCls(s.chg_5d,mx5d)+'">'+pct(s.chg_5d)+'</td>'
      +'<td class="'+heatCls(s.chg_20d,mx20d)+'">'+pct(s.chg_20d)+'</td>'
      +'<td>'+s.breadth+'%</td></tr>').join("");
    const rs=(d.rs_ranking||[]).map(x=>'<tr data-action="pick" data-arg="'+escapeHtml(x.ticker)+'" style="cursor:pointer"><td style="text-align:left;font-weight:700">'+escapeHtml(x.ticker)+'</td><td style="text-align:left;color:var(--muted)">'+escapeHtml(x.sector)+'</td>'
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
      + (ext && ext.summary && !ext.error
          ? '<div class="mono" style="margin-top:14px;font-size:12px;line-height:1.6"><b>Tekanan luar</b> · '+escapeHtml(ext.label||"")+' — '+escapeHtml(ext.summary)+'</div>'
          : '')
      +'<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Heatmap Sektor</div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Sektor</th><th>N</th><th>1D</th><th>5D</th><th>20D</th><th>Breadth</th></tr></thead><tbody>'+heat+'</tbody></table></div>'
      +'<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Relative Strength Ranking (20D)</div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Kode</th><th style="text-align:left">Sektor</th><th>1D</th><th>20D</th></tr></thead><tbody>'+rs+'</tbody></table></div>';
    showStatus("Selesai");
  }catch(e){ $("#mkResult").innerHTML='<div class="empty">Gagal: '+escapeHtml(e.message)+'</div>'; showStatus("Gagal"); }
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
      html += '<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Konsentrasi sektor</div>'
        + '<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Sektor</th><th>Nilai</th><th>Bobot</th></tr></thead><tbody>'
        + d.sectors.map(s=>'<tr><td style="text-align:left">'+escapeHtml(s.sector)+'</td><td>'+idr(s.value)+'</td><td>'+s.weight_pct+'%</td></tr>').join('')
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
        const body=cd.matrix.map((row,i)=>'<tr><td style="text-align:left;font-weight:700">'+cd.tickers[i]+'</td>'+row.map(v=>'<td style="color:'+(v>=0.7?'#ef5350':(v<=0.3?'#26a69a':'var(--muted)'))+'">'+v+'</td>').join('')+'</tr>').join("");
        html+='<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Korelasi 120D (&ge;0.7 merah = terlalu mirip)</div><div style="overflow-x:auto"><table>'+hdr+body+'</table></div>';
      } else { html+='<div class="mono" style="color:var(--muted);font-size:11px;margin-top:12px">Korelasi: '+cd.error+'</div>'; }
    }
    $("#pfRisk").innerHTML=html; showStatus("Selesai");
  }catch(e){ $("#pfRisk").innerHTML='<div class="empty">Gagal: '+escapeHtml(e.message)+'</div>'; showStatus("Gagal"); }
}

/* ---------- Trade journal ---------- */
let journal = LS.get("sbl_journal", []);
function renderJournal(){
  const el=$("#jrList");
  if(!journal.length){ el.innerHTML='<div class="empty" style="padding:24px">Belum ada catatan.</div>'; return; }
  el.innerHTML='<div style="overflow-x:auto"><table><thead><tr><th>Waktu</th><th style="text-align:left">Kode</th><th style="text-align:left">Catatan</th><th>Hasil</th><th></th></tr></thead><tbody>'
    +journal.map((j,i)=>'<tr><td>'+j.time+'</td><td style="text-align:left;font-weight:700;cursor:pointer" data-action="pick" data-arg="'+escapeHtml(j.ticker)+'">'+escapeHtml(j.ticker)+'</td><td style="text-align:left;color:var(--muted)">'+escapeHtml(j.note)+'</td><td class="'+(j.result>=0?'v-up':'v-red')+'">'+(j.result!=null?(j.result>=0?'+':'')+j.result+'%':'-')+'</td><td><button class="btn ghost" style="padding:3px 8px" data-action="jrRemove" data-idx="'+i+'">x</button></td></tr>').join('')
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

