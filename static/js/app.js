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
    const wu=d.weights_used||{};
    const wlabel=Object.keys(wu).length?Object.keys(wu).map(k=>k[0].toUpperCase()+k.slice(1)+' '+(wu[k]*100).toFixed(0)+'%').join(' · '):'bobot 40/30/15/15';
    const vrow=(label,val)=>'<div class="check" style="justify-content:space-between"><span>'+label+'</span><span class="mono '+(val>0?'v-up':(val<0?'v-red':'v-muted'))+'">'+(val>0?'+':'')+Number(val).toFixed(2)+'</span></div>';
    const cmp=(d.external&&d.external.x_compare)||null;
    const alignCls = cmp && cmp.alignment==="searah" ? "v-up" : (cmp && cmp.alignment==="berlawanan" ? "v-red" : "v-muted");
    const cmpHtml = cmp ? (
      '<div class="cmp"><div class="sec"><span class="badge">Komparasi '+escapeHtml(cmp.ticker||t)+'</span></div>'
      + '<div class="cmp-row">'
      + '<div><div class="k">Sinyal kita</div><div class="v">'+escapeHtml(cmp.our_signal||d.decision||"-")+'</div></div>'
      + '<div><div class="k">Suara X</div><div class="v">'+escapeHtml(cmp.theirs||"-")+'</div></div>'
      + '<div><div class="k">Hasil</div><div class="v '+alignCls+'">'+escapeHtml(cmp.alignment||"-")+'</div></div>'
      + '</div><p class="note">'+escapeHtml(cmp.note||"")+'</p></div>'
    ) : '';
    window.__myText = d.text;
    $("#myResult").innerHTML =
      '<div class="cmp-row">'
      +'<div><div class="k">Keputusan</div><div class="v '+cls+'">'+escapeHtml(d.decision)+'</div></div>'
      +'<div><div class="k">Konsensus</div><div class="v '+(d.consensus>0?'v-up':(d.consensus<0?'v-red':'v-muted'))+'">'+(d.consensus>0?'+':'')+d.consensus+'</div></div>'
      +'<div><div class="k">Conviction</div><div class="v">'+d.conviction+'%</div></div>'
      +'</div>'
      +'<div class="grid" style="margin-top:12px">'
      +'<div class="metric"><div class="k">Prob. model</div><div class="v v-muted">'+(d.ml_prob_up!=null?(d.ml_prob_up*100).toFixed(1)+'%':'tidak jalan')+'</div></div>'
      +'<div class="metric"><div class="k">Risk/Reward</div><div class="v v-muted">1:'+d.rr+'</div></div>'
      +'<div class="metric"><div class="k">Bandarmologi</div><div class="v '+(bstat==='DISTRIBUSI MASIF'?'v-red':'v-muted')+'">'+escapeHtml(bstat)+'</div></div>'
      +'<div class="metric"><div class="k">Entry</div><div class="v">'+idr(d.entry)+'</div></div>'
      +'<div class="metric"><div class="k">Target</div><div class="v v-up">'+idr(d.target)+'</div></div>'
      +'</div>'
      + '<p class="note">'+escapeHtml(d.ml_prob_up!=null
          ? ('Model uji '+((d.ml_test_accuracy!=null)?(d.ml_test_accuracy*100).toFixed(0)+'%':'-')
             +', dasar historis '+((d.ml_base_rate!=null)?(d.ml_base_rate*100).toFixed(0)+'%':'-')+'.')
          : ('Model tidak jalan: '+(d.ml_error||'tidak tersedia')+'.'))
        +' Bandarmologi dari volume, OBV, dan MFI, bukan transaksi sekuritas.</p>'
      + '<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:16px 0 4px">Vote agen ('+escapeHtml(wlabel)+')'+(d.has_financials===false?' · fundamental dikecualikan':'')+'</div>'
      + '<div class="my-votes">'+vrow('@technical',v.technical||0)+vrow('@bandarmologi',v.bandarmologi||0)+vrow('@fundamental',v.fundamental||0)+vrow('@sentiment',v.sentiment||0)+'</div>'
      + (d.external && d.external.summary ? '<p class="note" style="margin-top:12px"><b>@luar</b> '+escapeHtml(d.external.label||"")+' — '+escapeHtml(d.external.summary)+'</p>' : '')
      + cmpHtml
      + '<div class="my-log">'+String(d.text).replace(/</g,"&lt;")+'</div>'
      + '<div class="mono" style="color:var(--muted);font-size:10px;margin-top:8px">Engine: '+escapeHtml(d.engine||"")+'</div>';
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
    $("#myWeights").innerHTML = '<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px">Optimasi bobot technical:bandarmologi ('+d.tickers+' saham, '+d.tested+' kombinasi)</div>'
      + (d.best?'<div class="mono" style="color:var(--foreground);font-size:12px;margin-bottom:8px">Terbaik: technical '+d.best.w_technical+' : bandarmologi '+d.best.w_bandarmologi+' &middot; threshold '+d.best.threshold+' &middot; return rata-rata '+d.best.mean_return+'%</div>':'')
      + '<div style="overflow-x:auto"><table><thead><tr><th>#</th><th>Tech:Bandar</th><th>Thr</th><th>Return</th><th>PF</th><th>Win</th><th>Trade</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
      + '<div class="mono" style="color:var(--muted);font-size:10px;margin-top:10px">'+d.note+'</div>';
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
      +'<td style="text-align:left;color:var(--muted)">'+(((x.issues||[]).join('; '))||'-')+'</td></tr>').join("");
    $("#dqResult").innerHTML='<div class="mono" style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">Kualitas data: '+(d.ok)+'/'+(d.total)+' OK</div>'
      +'<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Kode</th><th>Bar</th><th>Terakhir</th><th>Status</th><th style="text-align:left">Catatan</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
    showStatus("Selesai");
  }catch(e){ $("#dqResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ $("#dqRun").disabled=false; }
}

/* ===================== UI/UX v2 ===================== */
function enhanceTables(){
  document.querySelectorAll("table:not(.as-cards)").forEach(function(tbl){
    if(tbl.hasAttribute("data-keep-scroll")) return;
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

function tapeSet(id, text){ var n=document.getElementById(id); if(n) n.textContent=text; }
function tapePx(n){
  var x=Number(n);
  if(!isFinite(x) || x<=0) return "—";
  return x.toLocaleString("id-ID", {maximumFractionDigits:1});
}
async function loadSummary(){
  var el=document.getElementById("summaryBar"); if(!el) return;
  var wl=(typeof watchlist!=="undefined" && watchlist)?watchlist.length:0;
  tapeSet("wlN", String(wl));
  try{
    var d=await (await fetch("/api/summary")).json();
    var ih=d.ihsg||{};
    var ret=Number(ih.ret_1d);
    var up=isFinite(ret) && ret>=0;
    var sc=(d.scans&&d.scans[0])||null;
    var sub=document.getElementById("ihsgSub");
    tapeSet("ihsgPx", tapePx(ih.price));
    if(sub){
      sub.className="sub "+(isFinite(ret)?(up?"v-up":"v-red"):"");
      sub.textContent=(isFinite(ret)?((up?"+":"")+ret.toFixed(2)+"% · "):"")+ (ih.regime||"tidak tersedia");
    }
    tapeSet("sigToday", String(d.signals_today||0));
    tapeSet("scanN", sc?String(sc.n):"—");
    tapeSet("scanSub", sc?((sc.universe||"").toUpperCase()+" · "+sc.buys+" beli"):"belum ada");
  }catch(e){
    tapeSet("ihsgPx", "—");
    tapeSet("ihsgSub", "tidak tersedia");
  }
}

var _onboardLastFocus=null;
function isOnboardOpen(){ var el=document.getElementById("onboard"); return !!(el && el.classList.contains("show")); }
function showOnboard(moveFocus){
  var el=document.getElementById("onboard"); if(!el) return;
  if(!isOnboardOpen()){ try{ _onboardLastFocus=document.activeElement; }catch(e){ _onboardLastFocus=null; } }
  el.classList.add("show");
  if(moveFocus){ var c=el.querySelector(".onboard-card"); if(c && c.focus){ try{ c.focus(); }catch(e){} } }
}
function focusHero(){ var i=document.getElementById("ticker"); if(!i) return; try{ i.focus(); }catch(e){} }
function hideOnboard(){ var el=document.getElementById("onboard"); if(el) el.classList.remove("show"); try{ localStorage.setItem("sbl_onboarded","1"); }catch(e){} focusHero(); }
function _onboardFocusables(el){
  return el.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
}
(function(){
  var b=document.getElementById("onboardClose"); if(b) b.onclick=hideOnboard;
  var h=document.getElementById("helpBtn"); if(h) h.onclick=function(){ showOnboard(true); };
  var o=document.getElementById("onboard"); if(o) o.addEventListener("click",function(e){ if(e.target.id==="onboard") hideOnboard(); });
  var seen=false; try{ seen=!!localStorage.getItem("sbl_onboarded"); }catch(e){ seen=true; }
  if(!seen) setTimeout(function(){ showOnboard(true); }, 700); else focusHero();
})();
document.addEventListener("keydown", function(e){
  if(!isOnboardOpen()) return;
  if(e.key==="Escape"){ e.preventDefault(); e.stopPropagation(); hideOnboard(); return; }
  if(e.key==="Tab"){
    var el=document.getElementById("onboard"); if(!el) return;
    var f=_onboardFocusables(el);
    if(!f.length){ e.preventDefault(); return; }
    var first=f[0], last=f[f.length-1], active=document.activeElement;
    if(el.contains(active)){
      if(e.shiftKey && active===first){ e.preventDefault(); last.focus(); }
      else if(!e.shiftKey && active===last){ e.preventDefault(); first.focus(); }
    } else {
      e.preventDefault(); first.focus();
    }
  }
}, true);

var TAB_ORDER=["analisis","fundamental","berita","screener","live","backtest","portofolio","akurasi","pasar","musyawarah"];
function gotoTabByIndex(i){ var name=TAB_ORDER[i]; if(!name) return; var t=document.querySelector('.tab[data-tab="'+name+'"]'); if(t) t.click(); }
document.addEventListener("keydown",function(e){
  if(isOnboardOpen()) return;
  if(typeof isNewsSheetOpen === "function" && isNewsSheetOpen()) return;
  var tag=(e.target.tagName||"").toLowerCase();
  if(tag==="input"||tag==="select"||tag==="textarea") return;
  if(e.key>="1"&&e.key<="9"){ gotoTabByIndex(Number(e.key)-1); }
  else if(e.key==="0"){ gotoTabByIndex(9); }
  else if(e.key==="/"){ e.preventDefault(); var inp=document.getElementById("ticker"); if(inp){ inp.focus(); if(inp.select) inp.select(); } }
  else if(e.key==="?"){ showOnboard(true); }
  else if(e.key==="t"||e.key==="T"){ var tb=document.getElementById("themeBtn"); if(tb) tb.click(); }
});

(function init(){
  try{ applyTheme(localStorage.getItem("sbl_theme") || "light"); }catch(e){}
  try{ if(typeof setIntro === "function") setIntro("analisis"); }catch(e){}
  if("serviceWorker" in navigator){ navigator.serviceWorker.register("/static/sw.js", {updateViaCache:"none"}).then(r=>r.update()).catch(()=>{}); }
  const yr = document.getElementById("yr"); if(yr) yr.textContent = new Date().getFullYear();
  const q = new URLSearchParams(location.search);
  if(q.get("ticker")){ $("#ticker").value = q.get("ticker").toUpperCase(); syncTicker(); }
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
  // Defer beban non-kritikal agar first paint & interaksi awal lebih cepat.
  const defer = (fn)=> (window.requestIdleCallback ? requestIdleCallback(fn) : setTimeout(fn, 400));
  defer(()=>{
    loadSummary();
    fetch("/api/llm/status").then(r=>r.json()).then(s=>{ const el=$("#myLlmStatus"); if(el){ const p = s.prompt_file ? ("berkas " + s.prompt_file + " — edit berkas ini / set LLM_PROMPT_PATH") : "bawaan — set LLM_PROMPT_PATH untuk memakai berkas sendiri"; el.textContent = "Mode LLM: " + (s.configured ? ("siap (" + s.model + ")") : "belum dikonfigurasi (set OPENAI_API_KEY / LLM_API_KEY)") + " | prompt MD: " + p; } }).catch(()=>{});
    renderWatchlist(); renderPositions(); renderAlerts(); loadHistory(); pollPortfolio();
    loadPaper(); loadDb();
    setInterval(pollPortfolio, 20000);
    setInterval(loadSummary, 60000);
  });
})();
analyze();
