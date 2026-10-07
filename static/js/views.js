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

/* ---------- Tab: Fundamental ---------- */
function syncFuInputs(){
  const src=($("#ticker").value||"").trim().toUpperCase();
  ["#fuTicker","#beTicker"].forEach(sel=>{ const el=$(sel); if(el && !el.dataset.touched && src) el.value=src; });
}
function fuVerdict(f){
  const out=[];
  let val="Cukup";
  if(f.pe!=null){ if(f.pe>0 && f.pe<15) val="Murah"; else if(f.pe>30) val="Mahal"; }
  out.push(["Valuasi", val, val==="Murah"?"v-up":(val==="Mahal"?"v-red":"v-muted")]);
  let prof="Cukup";
  if(f.roe!=null){ prof = f.roe>=0.15?"Baik":(f.roe<0.05?"Kurang":"Cukup"); }
  else if(f.profit_margin!=null){ prof = f.profit_margin>=0.10?"Baik":(f.profit_margin<0.03?"Kurang":"Cukup"); }
  out.push(["Profitabilitas", prof, prof==="Baik"?"v-up":(prof==="Kurang"?"v-red":"v-muted")]);
  let lev="Sedang";
  if(f.der!=null){ lev = f.der<=50?"Rendah":(f.der>150?"Tinggi":"Sedang"); }
  out.push(["Leverage (DER)", lev, lev==="Rendah"?"v-up":(lev==="Tinggi"?"v-red":"v-muted")]);
  let grow="Stabil";
  const gr=(f.revenue_growth!=null&&f.earnings_growth!=null)?(f.revenue_growth+f.earnings_growth)/2:(f.revenue_growth!=null?f.revenue_growth:f.earnings_growth);
  if(gr!=null){ grow = gr>=0.15?"Tumbuh":(gr<0?"Turun":"Stabil"); }
  out.push(["Pertumbuhan", grow, grow==="Tumbuh"?"v-up":(grow==="Turun"?"v-red":"v-muted")]);
  return out;
}
async function loadFundamentalTab(){
  const t=($("#fuTicker").value||"").trim().toUpperCase(); const el=$("#fuResult"); if(!el) return;
  if(!t){ el.innerHTML='<div class="card empty">Masukkan kode saham.</div>'; return; }
  el.innerHTML='<div class="card empty">Memuat fundamental '+t+'...</div>';
  showStatus("Memuat fundamental "+t+"...", true);
  try{
    const f=await (await fetch('/api/fundamental?ticker='+encodeURIComponent(t))).json();
    if(f.error) throw new Error(f.error);
    const num=(v,d=2)=> v==null?"-":Number(v).toFixed(d);
    const pct=(v)=> v==null?"-":(Number(v)*100).toFixed(2)+"%";
    const dy=(v)=> v==null?"-":Number(v).toFixed(2)+"%";
    const cap=(v)=> v==null?"-":(Math.abs(Number(v))>=1e12? (Number(v)/1e12).toFixed(2)+" T": (Number(v)/1e9).toFixed(2)+" M");
    const rp=(v)=> v==null?"-":idr(v);
    const m=(k,v,cls)=> '<div class="metric"><div class="k">'+k+'</div><div class="v '+(cls||'v-muted')+'">'+v+'</div></div>';
    const hd='<div class="mono" style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:.06em;margin:18px 0 8px">';
    const verdict=fuVerdict(f).map(x=>m(x[0], x[1], x[2])).join('');
    const rangePos=(f.price!=null&&f.high_52w!=null&&f.low_52w!=null&&f.high_52w>f.low_52w)?Math.round((f.price-f.low_52w)/(f.high_52w-f.low_52w)*100):null;
    el.innerHTML =
      '<div class="card">'
      + '<div class="sec"><span class="badge">'+(f.name||t)+'</span></div>'
      + '<p class="muted" style="margin:-4px 0 14px;font-size:12px">'+[f.sector,f.industry].filter(Boolean).join(' · ')+'</p>'
      + '<div class="grid">'+verdict+'</div>'
      + hd+'Valuasi</div>'
      + '<div class="grid">'
      + m("PER (TTM)", num(f.pe))
      + m("PER Forward", num(f.pe_forward))
      + m("PBV", num(f.pb))
      + m("P/S", num(f.ps))
      + m("PEG", num(f.peg))
      + m("Market Cap", cap(f.market_cap), "v-white")
      + '</div>'
      + hd+'Profitabilitas</div>'
      + '<div class="grid">'
      + m("ROE", pct(f.roe), (f.roe||0)>=0.15?"v-up":"v-muted")
      + m("Margin Laba", pct(f.profit_margin), (f.profit_margin||0)>=0.1?"v-up":"v-muted")
      + m("Margin Kotor", pct(f.gross_margin))
      + m("Margin Operasi", pct(f.operating_margin))
      + m("EPS", num(f.eps), "v-white")
      + m("Laba Bersih", cap(f.net_income))
      + '</div>'
      + hd+'Neraca &amp; Risiko</div>'
      + '<div class="grid">'
      + m("DER", num(f.der))
      + m("Current Ratio", num(f.current_ratio))
      + m("Kas", cap(f.cash))
      + m("Total Utang", cap(f.debt))
      + m("Beta", num(f.beta))
      + m("Dividen", dy(f.dividend_yield), "v-up")
      + '</div>'
      + hd+'Pertumbuhan</div>'
      + '<div class="grid">'
      + m("Pertumbuhan Pendapatan", pct(f.revenue_growth), (f.revenue_growth||0)>=0?"v-up":"v-red")
      + m("Pertumbuhan Laba", pct(f.earnings_growth), (f.earnings_growth||0)>=0?"v-up":"v-red")
      + m("Pendapatan", cap(f.revenue))
      + m("EBITDA", cap(f.ebitda))
      + m("Free Cash Flow", cap(f.free_cashflow))
      + m("Nilai Buku / Saham", num(f.book_value))
      + '</div>'
      + hd+'Rentang Harga</div>'
      + '<div class="grid">'
      + m("Harga", rp(f.price), "v-white")
      + m("52w High", rp(f.high_52w), "v-red")
      + m("52w Low", rp(f.low_52w), "v-up")
      + m("Posisi 52w", rangePos==null?"-":rangePos+"%")
      + '</div>'
      + '<p class="note">Penilaian bersifat heuristik dari rasio, bukan rekomendasi. Angka "-" berarti data tidak tersedia di yfinance.</p>'
      + '</div>';
    showStatus("Selesai");
  }catch(e){ el.innerHTML='<div class="card empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
}

/* ---------- Tab: Berita ---------- */
function fmtNewsTime(ts){
  if(ts==null) return "";
  const d = (typeof ts==="number") ? new Date(ts*1000) : new Date(ts);
  if(isNaN(d.getTime())) return "";
  return d.toLocaleString("id-ID",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"});
}
async function loadNewsTab(){
  const t=($("#beTicker").value||"").trim().toUpperCase(); const el=$("#beResult"); if(!el) return;
  if(!t){ el.innerHTML='<div class="card empty">Masukkan kode saham.</div>'; return; }
  el.innerHTML='<div class="card empty">Memuat berita '+t+'...</div>';
  showStatus("Memuat berita "+t+"...", true);
  try{
    const n=await (await fetch('/api/news?ticker='+encodeURIComponent(t))).json();
    if(n.error) throw new Error(n.error);
    const cls = n.label==="Positif"?"v-up":(n.label==="Negatif"?"v-red":"v-muted");
    const items=(n.items||[]).map(it=>{
      const s = it.sentiment>=0.2?"v-up":(it.sentiment<=-0.2?"v-red":"v-muted");
      const arrow = it.sentiment>0?"▲":(it.sentiment<0?"▼":"•");
      const title = it.url ? '<a href="'+it.url+'" target="_blank" rel="noreferrer" style="color:var(--brand-dark);text-decoration:none">'+(it.title||"-")+'</a>' : (it.title||"-");
      return '<div class="check" style="align-items:flex-start;gap:10px">'
        + '<span class="ic '+s+'">'+arrow+'</span>'
        + '<span style="flex:1;font-family:var(--ui-font);white-space:normal;line-height:1.55">'+title
        + '<br><span class="mono" style="color:var(--muted);font-size:10px">'+[(it.publisher||""),fmtNewsTime(it.time)].filter(Boolean).join(" · ")+'</span></span></div>';
    }).join("");
    el.innerHTML =
      '<div class="card">'
      + '<div class="grid">'
      + '<div class="metric hl"><div class="k">Sentimen</div><div class="v '+cls+'">'+n.label+'</div></div>'
      + '<div class="metric"><div class="k">Skor rata-rata</div><div class="v v-muted">'+(n.avg_sentiment==null?"-":Number(n.avg_sentiment).toFixed(2))+'</div></div>'
      + '<div class="metric"><div class="k">Jumlah berita</div><div class="v v-white">'+n.count+'</div></div>'
      + '</div>'
      + (items? '<div class="mono" style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:.06em;margin:18px 0 6px">Daftar berita</div><div>'+items+'</div>'
               : '<div class="empty" style="padding:24px">Tidak ada berita untuk '+t+'.</div>')
      + '</div>';
    showStatus("Selesai");
  }catch(e){ el.innerHTML='<div class="card empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
}
if($("#fuRun")) $("#fuRun").onclick=loadFundamentalTab;
if($("#fuTicker")){
  $("#fuTicker").addEventListener("keydown",e=>{ if(e.key==="Enter") loadFundamentalTab(); });
  $("#fuTicker").addEventListener("input",e=>{ e.target.dataset.touched="1"; });
}
if($("#beRun")) $("#beRun").onclick=loadNewsTab;
if($("#beTicker")){
  $("#beTicker").addEventListener("keydown",e=>{ if(e.key==="Enter") loadNewsTab(); });
  $("#beTicker").addEventListener("input",e=>{ e.target.dataset.touched="1"; });
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

