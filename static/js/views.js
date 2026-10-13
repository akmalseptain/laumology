/* ---------- Auto-scan + external notify ---------- */
let autoScanTimer=null;
let asSnapshot=LS.get("sbl_autoscan_snap",{});
function setAsStatus(txt){ const el=$("#asStatus"); if(el) el.textContent=txt; }
function renderAsResult(rows){
  const top=(rows||[]).filter(x=>x.Signal==="STRONG BUY"||x.Signal==="BUY").slice(0,20);
  $("#asResult").innerHTML = top.length ? '<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Kode</th><th>Skor</th><th>Sinyal</th><th>Aksi</th></tr></thead><tbody>'
    + top.map(x=>'<tr data-action="pick" data-arg="'+escapeHtml(x.Ticker)+'" style="cursor:pointer"><td style="text-align:left;font-weight:700">'+escapeHtml(x.Ticker)+'</td><td>'+x.Score+'</td><td><span class="tag s-'+signalClass(x.Signal)+'">'+x.Signal+'</span></td><td style="color:var(--muted)">'+x.Action+'</td></tr>').join('')
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
  el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Model ML (logistic)</span></div><div class="empty">Melatih model...</div></div>';
  try{
    const m = await (await fetch('/api/ml?ticker=' + encodeURIComponent(t) + '&horizon=10')).json();
    if(m.error) throw new Error(m.error);
    const pct = (v) => v==null?"-":(Number(v)*100).toFixed(1)+"%";
    const prob = m.current_prob_up;
    const cls = prob>=0.6?"v-up":(prob<=0.4?"v-red":"v-muted");
    const wrows = (m.weights||[]).slice(0,8).map((w,i)=>'<div class="check" style="justify-content:space-between"><span>'+(i+1)+'. '+w.factor+'</span><span class="mono '+(w.weight>=0?'v-up':'v-red')+'">'+(w.weight>=0?'+':'')+w.weight+'</span></div>').join("");
    el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Model ML (logistic)</span></div>'
      + '<div class="grid">'
      + '<div class="metric hl"><div class="k">Probabilitas Naik</div><div class="v '+cls+'">'+pct(prob)+'</div></div>'
      + '<div class="metric"><div class="k">Akurasi (out-of-sample)</div><div class="v v-white">'+pct(m.test_accuracy)+'</div></div>'
      + '<div class="metric"><div class="k">Base Rate</div><div class="v v-muted">'+pct(m.base_rate)+'</div></div>'
      + '<div class="metric"><div class="k">Edge vs Base</div><div class="v '+(m.edge_vs_base>=0?'v-up':'v-red')+'">'+(m.edge_vs_base==null?'-':(m.edge_vs_base>=0?'+':'')+pct(m.edge_vs_base))+'</div></div>'
      + '<div class="metric"><div class="k">Sampel / Train / Test</div><div class="v v-muted">'+m.samples+' / '+m.train+' / '+m.test+'</div></div>'
      + '</div>'
      + '<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 6px">Bobot faktor (kontribusi)</div>'
      + '<div class="checks" style="grid-template-columns:1fr">'+wrows+'</div>'
      + '<div class="mono" style="color:var(--muted);font-size:10px;margin-top:10px">Heuristik statistik (bukan jaminan). Probabilitas = peluang historis naik dalam 10 bar.</div>'
      + '</div>';
  }catch(e){ el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Model ML</span></div><div class="empty">Gagal: '+e.message+'</div></div>'; }
}

/* ---------- Berita: renderer bersama + sheet detail (W-0010) ---------- */
/* Ambang sentimen disatukan dengan label Python (news.py _summarize: ±0.15)
   agar badge kartu konsisten dengan ringkasan backend (bukan ±0.2 terpisah). */
const NEWS_THRESHOLD = 0.15;
/* Batas penyimpanan data kartu berita. Wajib > jumlah kartu satu render agar
   kartu yang sedang tampil tak ikut terbuang saat eviksi berbutir. Maksimum
   satu render saat ini 24 (`news.py get_market_news`) dan 15 (`get_news`),
   jadi 200 aman; `_newsEvict` juga menaikkan batas bila satu batch lebih besar. */
const NEWS_STORE_CAP = 200;
const _newsStore = new Map();
let _newsSeq = 0;
let _newsSheetOpen = false;
let _newsLastFocus = null;
let _newsZoomOpen = false;
let _newsZoomTrigger = null;

function newsVerdict(it){
  const raw = Number(it && it.sentiment);
  const score = isNaN(raw) ? 0 : raw;
  const pos = Number((it && it.pos) || 0);
  const neg = Number((it && it.neg) || 0);
  if(score > NEWS_THRESHOLD) return {score:score,pos:pos,neg:neg,label:"Positif",cls:"v-up",arrow:"▲"};
  if(score < -NEWS_THRESHOLD) return {score:score,pos:pos,neg:neg,label:"Negatif",cls:"v-red",arrow:"▼"};
  return {score:score,pos:pos,neg:neg,label:"Netral",cls:"v-muted",arrow:"•"};
}
function newsThumbHtml(it){
  const fallback = '<span class="news-thumb-fallback" aria-hidden="true">'
    + '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M4 5h13v14H4z"/><path d="M17 8h3v11h-3"/><path d="M7 9h7M7 12h7M7 15h4"/></svg></span>';
  const img = safeUrl(it && it.image);
  if(!img) return '<span class="news-thumb">'+fallback+'</span>';
  return '<span class="news-thumb">'+fallback
    + '<img class="news-thumb-img" src="'+escapeHtml(img)+'" alt="" loading="lazy" referrerpolicy="no-referrer"></span>';
}
function newsSummary(it){
  /* Gate tunggal "ringkasan bermakna" dipakai kartu & sheet agar tak drift.
     Ambang 24 selaras `news._MIN_SUMMARY`; ringkasan yang cuma mengulang judul
     dianggap tak bermakna. */
  const summary = String((it && it.summary) || "").trim();
  const rawTitle = String((it && it.title) || "").trim();
  const meaningful = summary.length >= 24 && summary.toLowerCase() !== rawTitle.toLowerCase();
  return meaningful ? summary : "";
}
function newsSummaryHtml(it){
  const summary = newsSummary(it);
  /* Wajib <span> bergaya block: `.news-item` adalah <button> yang hanya boleh
     phrasing content, jadi <p> akan memicu auto-repair DOM. */
  return summary ? '<span class="news-item-summary">'+escapeHtml(summary)+'</span>' : '';
}
function newsCardHtml(it){
  const id = "n" + (++_newsSeq);
  _newsStore.set(id, it || {});
  const v = newsVerdict(it);
  const src = (it && it.source_ticker) ? escapeHtml(it.source_ticker) : "";
  const meta = [escapeHtml((it && it.publisher) || ""), fmtNewsTime(it && it.time), src].filter(Boolean).join(" · ");
  const title = escapeHtml((it && it.title) || "(Tanpa judul)");
  const summaryHtml = newsSummaryHtml(it);
  const summaryText = newsSummary(it);
  /* Ringkasan ikut dibacakan screen reader: tanpa ini `aria-label` menimpa isi
     tombol sehingga teks ringkasan yang tampak justru bisu. */
  const aria = "Baca detail: " + title + (summaryText ? ". " + escapeHtml(summaryText) : "");
  return '<button type="button" class="news-item'+(summaryHtml?' has-summary':'')+'" data-news-id="'+id+'" aria-label="'+aria+'">'
    + newsThumbHtml(it)
    + '<span class="news-item-body"><span class="news-item-title">'+title+'</span>'
    + summaryHtml
    + (meta ? '<span class="news-item-meta mono">'+meta+'</span>' : '')
    + '</span><span class="ic '+v.cls+' news-item-badge" aria-hidden="true">'+v.arrow+'</span></button>';
}
function _newsEvict(batchSize){
  /* Eviksi berbutir SETELAH insert penuh: buang entri tertua sampai ukuran
     kembali ke batas. Batas = max(NEWS_STORE_CAP, ukuran batch) supaya kartu
     yang baru dirender di batch yang sama tak ikut terbuang. */
  const cap = Math.max(NEWS_STORE_CAP, Number(batchSize) || 0);
  while(_newsStore.size > cap){
    const oldest = _newsStore.keys().next().value;
    if(oldest === undefined) break;
    _newsStore.delete(oldest);
  }
}
function newsCardsHtml(items){
  const list = items || [];
  const arr = list.map(function(it){ return newsCardHtml(it); }).join("");
  _newsEvict(list.length);
  return arr ? '<div class="news-list">'+arr+'</div>' : "";
}
function newsConclusionText(v){
  let basis;
  if(v.pos && v.neg) basis = "Judul memuat "+v.pos+" kata positif dan "+v.neg+" kata negatif.";
  else if(v.pos) basis = "Judul memuat "+v.pos+" kata positif.";
  else if(v.neg) basis = "Judul memuat "+v.neg+" kata negatif.";
  else basis = "Tidak ditemukan kata sentimen pada judul.";
  const verdict = v.label==="Positif" ? "Kecenderungan positif."
    : (v.label==="Negatif" ? "Kecenderungan negatif." : "Netral / belum signifikan.");
  return basis + " " + verdict;
}
function newsSheetHtml(it){
  const v = newsVerdict(it);
  const url = safeUrl(it && it.url);
  const img = safeUrl(it && it.image);
  const title = escapeHtml((it && it.title) || "(Tanpa judul)");
  const src = (it && it.source_ticker) ? escapeHtml(it.source_ticker) : "";
  const meta = [escapeHtml((it && it.publisher) || ""), fmtNewsTime(it && it.time), src].filter(Boolean).join(" · ");
  const summary = newsSummary(it);
  const summaryHtml = summary
    ? '<p class="news-sheet-para">'+escapeHtml(summary)+'</p>'
    : '<p class="news-sheet-para muted">Ringkasan tidak tersedia dari sumber berita — buka berita untuk detail lengkap.</p>';
  const imgHtml = img
    ? '<button type="button" class="news-sheet-img-btn" data-src="'+escapeHtml(img)+'" aria-label="Perbesar gambar berita">'
      + '<img class="news-sheet-img" src="'+escapeHtml(img)+'" alt="" loading="lazy" referrerpolicy="no-referrer">'
      + '<span class="news-sheet-img-badge" aria-hidden="true">Klik untuk perbesar</span></button>'
    : '';
  const link = url
    ? '<a class="btn news-sheet-link" href="'+escapeHtml(url)+'" target="_blank" rel="noreferrer" referrerpolicy="no-referrer">Lihat berita</a>'
    : '<span class="btn ghost news-sheet-link disabled" aria-disabled="true">Tautan tidak tersedia</span>';
  /* Gambar didahulukan agar visual langsung tampil SEBELUM judul/meta; gambar
     yang gagal dimuat disembunyikan listener error global (views.js `error`),
     jadi tak ada tombol/ruang kosong menggantung. */
  return imgHtml
    + '<h3 class="news-sheet-title">'+title+'</h3>'
    + (meta ? '<div class="news-sheet-meta mono">'+meta+'</div>' : '')
    + '<div class="news-sheet-label mono">Kejelasan singkat</div>'
    + summaryHtml
    + '<div class="news-sheet-label mono">Kesimpulan sentimen</div>'
    + '<div class="news-sheet-verdict '+v.cls+'">'+v.label+' · skor '+v.score.toFixed(2)+' (positif '+v.pos+' / negatif '+v.neg+')</div>'
    + '<p class="news-sheet-para">'+escapeHtml(newsConclusionText(v))+'</p>'
    + '<div class="news-sheet-actions">'+link+'</div>';
}
function newsSheetEl(){ return document.getElementById("newsSheet"); }
function isNewsSheetOpen(){ return _newsSheetOpen; }
function openNewsSheet(it){
  const sheet = newsSheetEl(); if(!sheet || !it) return;
  const body = document.getElementById("newsSheetBody");
  if(body) body.innerHTML = newsSheetHtml(it);
  _newsLastFocus = document.activeElement;
  sheet.classList.add("show");
  sheet.setAttribute("aria-hidden","false");
  _newsSheetOpen = true;
  document.body.classList.add("news-sheet-open");
  const closeBtn = sheet.querySelector(".news-sheet-close");
  if(closeBtn) closeBtn.focus();
}
function closeNewsSheet(){
  const sheet = newsSheetEl(); if(!sheet) return;
  sheet.classList.remove("show");
  sheet.setAttribute("aria-hidden","true");
  _newsSheetOpen = false;
  document.body.classList.remove("news-sheet-open");
  const back = _newsLastFocus;
  _newsLastFocus = null;
  if(back && back.focus){ try{ back.focus(); }catch(e){} }
}
function _newsFocusables(sheet){
  return sheet.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
}
function newsZoomEl(){ return document.querySelector(".news-zoom"); }
function newsZoomHtml(src){
  return '<button type="button" class="news-zoom-close" aria-label="Tutup gambar diperbesar">&times;</button>'
    + '<img class="news-zoom-img" src="'+escapeHtml(src)+'" alt="" referrerpolicy="no-referrer">';
}
function openNewsZoom(rawSrc, trigger){
  const src = safeUrl(rawSrc);
  if(!src || newsZoomEl()) return;
  const overlay = document.createElement("div");
  overlay.className = "news-zoom";
  overlay.setAttribute("role","dialog");
  overlay.setAttribute("aria-modal","true");
  overlay.setAttribute("aria-label","Gambar berita diperbesar");
  overlay.innerHTML = newsZoomHtml(src);
  _newsZoomTrigger = trigger || null;
  _newsZoomOpen = true;
  document.body.appendChild(overlay);
  const closeBtn = overlay.querySelector(".news-zoom-close");
  if(closeBtn) closeBtn.focus();
}
function closeNewsZoom(){
  if(!_newsZoomOpen) return;
  _newsZoomOpen = false;
  const overlay = newsZoomEl();
  if(overlay) overlay.remove();
  const back = _newsZoomTrigger;
  _newsZoomTrigger = null;
  if(back && back.focus){ try{ back.focus(); }catch(e){} }
}
document.addEventListener("click", function(e){
  const t = e.target;
  if(!t || !t.closest) return;
  if(t.closest(".news-zoom-close")){ e.preventDefault(); closeNewsZoom(); return; }
  const zoom = newsZoomEl();
  if(zoom && t === zoom){ closeNewsZoom(); return; }
  const zoomBtn = t.closest(".news-sheet-img-btn");
  if(zoomBtn){
    e.preventDefault();
    const img = zoomBtn.querySelector(".news-sheet-img");
    openNewsZoom(zoomBtn.getAttribute("data-src") || (img && img.getAttribute("src")), zoomBtn);
    return;
  }
  if(t.closest(".news-sheet-close")){ closeNewsSheet(); return; }
  const card = t.closest(".news-item");
  if(card){
    e.preventDefault();
    const it = _newsStore.get(card.getAttribute("data-news-id"));
    if(it) openNewsSheet(it);
    return;
  }
  const sheet = newsSheetEl();
  if(sheet && t === sheet) closeNewsSheet();
});
document.addEventListener("keydown", function(e){
  if(_newsZoomOpen){
    const z = newsZoomEl();
    if(e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); closeNewsZoom(); return; }
    if(e.key === "Tab" && z){
      const f = _newsFocusables(z);
      if(!f.length){ e.preventDefault(); return; }
      const first = f[0], last = f[f.length-1], active = document.activeElement;
      if(!z.contains(active)){ e.preventDefault(); first.focus(); }
      else if(e.shiftKey && active === first){ e.preventDefault(); last.focus(); }
      else if(!e.shiftKey && active === last){ e.preventDefault(); first.focus(); }
      return;
    }
  }
  if(!_newsSheetOpen) return;
  const sheet = newsSheetEl(); if(!sheet) return;
  if(e.key === "Escape"){ e.preventDefault(); closeNewsSheet(); return; }
  if(e.key === "Tab"){
    const f = _newsFocusables(sheet);
    if(!f.length) return;
    const first = f[0], last = f[f.length-1], active = document.activeElement;
    if(e.shiftKey && active === first){ e.preventDefault(); last.focus(); }
    else if(!e.shiftKey && active === last){ e.preventDefault(); first.focus(); }
  }
}, true);
document.addEventListener("error", function(e){
  const el = e.target;
  if(!el || !el.classList) return;
  if(el.classList.contains("news-zoom-img")){ closeNewsZoom(); return; }
  if(el.classList.contains("news-thumb-img")){ el.style.display = "none"; return; }
  if(el.classList.contains("news-sheet-img")){
    const btn = el.closest && el.closest(".news-sheet-img-btn");
    if(btn) btn.style.display = "none"; else el.style.display = "none";
  }
}, true);

async function loadNews(t){
  const el = document.getElementById("newsCard"); if(!el) return;
  el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Sentimen Berita</span></div><div class="empty">Memuat berita...</div></div>';
  try{
    const n = await (await fetch('/api/news?ticker=' + encodeURIComponent(t))).json();
    if(n.error) throw new Error(n.error);
    const cls = n.label==="Positif"?"v-up":(n.label==="Negatif"?"v-red":"v-muted");
    const items = newsCardsHtml((n.items||[]).slice(0,8));
    el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Sentimen Berita</span></div>'
      + '<div class="grid"><div class="metric hl"><div class="k">Sentimen</div><div class="v '+cls+'">'+n.label+'</div></div>'
      + '<div class="metric"><div class="k">Skor rata-rata</div><div class="v v-muted">'+n.avg_sentiment+'</div></div>'
      + '<div class="metric"><div class="k">Jumlah berita</div><div class="v v-white">'+n.count+'</div></div></div>'
      + (items ? '<div style="margin-top:12px">'+items+'</div>' : (n.degraded ? '<div class="empty" style="padding:20px">Gagal memuat berita (sumber tidak tersedia).</div>' : '<div class="empty" style="padding:20px">Tidak ada berita.</div>'))
      + '</div>';
  }catch(e){ el.innerHTML = '<div class="card"><div class="sec"><span class="badge">Sentimen Berita</span></div><div class="empty">Gagal: '+e.message+'</div></div>'; }
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
    const unavailable = f.available === false;
    const priceOnly = f.available === true && f.has_financials === false;
    const fuBadge = unavailable ? ' <span class="badge" style="color:var(--down)">Data fundamental tidak tersedia</span>'
      : (priceOnly ? ' <span class="badge" style="color:var(--muted)">Hanya harga tersedia; rasio fundamental kosong</span>' : '');
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
      + '<div class="sec"><span class="badge">'+(f.name||t)+'</span>'+fuBadge+'</div>'
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
      + '<p class="note">'+(unavailable?'Data fundamental tidak tersedia dari sumber (kosong/rate-limit); angka "-" bukan berarti nol. ':(priceOnly?'Hanya harga tersedia dari sumber; rasio fundamental (PER/PBV/ROE) kosong. ':''))+'Penilaian bersifat heuristik dari rasio, bukan rekomendasi. Angka "-" berarti data tidak tersedia di yfinance.</p>'
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
  el.innerHTML='<div class="card empty">Memuat berita '+escapeHtml(t)+'...</div>';
  showStatus("Memuat berita "+t+"...", true);
  try{
    const n=await (await fetch('/api/news?ticker='+encodeURIComponent(t))).json();
    if(n.error) throw new Error(n.error);
    const cls = n.label==="Positif"?"v-up":(n.label==="Negatif"?"v-red":"v-muted");
    const items=newsCardsHtml(n.items||[]);
    el.innerHTML =
      '<div class="card">'
      + '<div class="grid">'
      + '<div class="metric hl"><div class="k">Sentimen</div><div class="v '+cls+'">'+n.label+'</div></div>'
      + '<div class="metric"><div class="k">Skor rata-rata</div><div class="v v-muted">'+(n.avg_sentiment==null?"-":Number(n.avg_sentiment).toFixed(2))+'</div></div>'
      + '<div class="metric"><div class="k">Jumlah berita</div><div class="v v-white">'+n.count+'</div></div>'
      + '</div>'
      + (items? '<div class="mono" style="color:var(--muted);font-size:11px;font-weight:600;letter-spacing:.06em;margin:18px 0 6px">Daftar berita</div>'+items
               : (n.degraded ? '<div class="empty" style="padding:24px">Gagal memuat berita untuk '+escapeHtml(t)+' (sumber tidak tersedia).</div>'
                             : '<div class="empty" style="padding:24px">Tidak ada berita untuk '+escapeHtml(t)+'.</div>'))
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
    $("#optResult").innerHTML = '<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px">Optimizer ('+d.tested+' kombinasi)</div>'
      + (b ? '<div class="mono" style="color:var(--foreground);font-size:12px;margin-bottom:8px">Terbaik: min_skor '+b.min_score+' · TP RR '+b.tp_rr+' · SL x ATR '+b.sl_mult+'</div>' : '')
      + '<div style="overflow-x:auto"><table><thead><tr><th>#</th><th>MinSkor</th><th>TP RR</th><th>SL ATR</th><th>Return</th><th>PF</th><th>Trade</th><th>Win</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
      + '<div class="mono" style="color:var(--muted);font-size:10px;margin-top:10px">Hati-hati overfitting: validasi dengan Walk-forward.</div>';
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
          return '<tr><td style="font-weight:700;cursor:pointer" data-action="pick" data-arg="'+escapeHtml(r.ticker)+'">'+escapeHtml(r.ticker)+'</td>'
            +'<td>'+fmt(r.entry)+'</td><td>'+r.lots+'</td><td>'+(r.last!=null?idr(r.last):"-")+'</td>'
            +'<td class="'+cls+'">'+(pnl!=null?(pnl>=0?'+':'')+idr(pnl)+(r.pnl_pct!=null?' ('+(r.pnl_pct>=0?'+':'')+fmt(r.pnl_pct,2)+'%)':''):'-')+'</td>'
            +'<td>'+(r.status==='OPEN'?'<span class="tag s-BUY">OPEN</span>':(r.pnl>=0?'<span class="tag s-BUY">CLOSED +</span>':'<span class="tag s-SELL">CLOSED -</span>'))+'</td>'
            +'<td>'+(r.status==='OPEN'?'<button class="btn ghost" style="padding:3px 8px" data-action="ppClose" data-arg="'+escapeHtml(r.id)+'">Tutup</button>':'')+'</td></tr>';
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
    const srows=(sg.rows||[]).map(x=>'<tr><td>'+x.ts.slice(5,16)+'</td><td style="text-align:left;font-weight:700;cursor:pointer" data-action="pick" data-arg="'+escapeHtml(x.ticker)+'">'+escapeHtml(x.ticker)+'</td><td><span class="tag s-'+signalClass(x.signal)+'">'+x.signal+'</span></td><td>'+x.score+'</td><td>'+x.source+'</td></tr>').join("");
    const crows=(sc.rows||[]).map(x=>'<tr><td>'+x.ts.slice(5,16)+'</td><td style="text-align:left">'+x.universe+'</td><td>'+x.n+'</td><td>'+x.buys+'</td></tr>').join("");
    el.innerHTML = '<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">Sinyal tersimpan</div>'
      + (srows?'<div style="overflow-x:auto"><table><thead><tr><th>Waktu</th><th>Kode</th><th>Sinyal</th><th>Skor</th><th>Sumber</th></tr></thead><tbody>'+srows+'</tbody></table></div>':'<div class="empty" style="padding:14px">Kosong. Jalankan scheduler.py atau analisis manual.</div>')
      + '<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 6px">Log scan otomatis</div>'
      + (crows?'<div style="overflow-x:auto"><table><thead><tr><th>Waktu</th><th>Universe</th><th>Discan</th><th>Beli</th></tr></thead><tbody>'+crows+'</tbody></table></div>':'<div class="empty" style="padding:14px">Belum ada scan otomatis (jalankan <b>py scheduler.py</b>).</div>');
  }catch(e){ el.innerHTML='<div class="empty">Gagal memuat.</div>'; }
}

