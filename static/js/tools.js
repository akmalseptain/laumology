/* ---------- Export & reporting ---------- */
let lastAnalysis = null;
function exportCsv(){
  const d = lastAnalysis;
  if(!d){ showStatus("Belum ada analisis"); return; }
  const rows = [
    ["Ticker", d.ticker], ["Interval", d.interval], ["Harga", d.price],
    ["Perubahan 1D (%)", d.change_1d], ["Sinyal", d.signal], ["Aksi", d.action],
    ["Skor", d.score], ["Confidence", d.confidence], ["Grade", d.grade],
    ["Skor Heuristik", d.score_heuristic], ["Skor Optimal", d.score_opt],
    ["Prob Up (ML)", d.prob_up], ["Model Terpakai", d.model_used ? "YA" : "TIDAK"],
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
    ["Hull MA 20", d.hma20], ["KAMA", d.kama],
    ["Aroon Up", d.aroon_up], ["Aroon Down", d.aroon_down],
    ["Vortex+", d.vortex_plus], ["Vortex-", d.vortex_minus],
    ["Awesome Osc", d.ao], ["Ultimate Osc", d.uo], ["RVOL", d.rvol],
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
function acHorizonLabel(h){
  if(h===1) return "Harian (1 bar)";
  if(h>=5 && h<=10) return "Swing ("+h+" bar)";
  if(h>=11 && h<=20) return "3-Mingguan ("+h+" bar)";
  return h+" bar";
}
function acReliabilityBadge(rel){
  const r=rel||{}, lvl=r.level;
  const tip='signifikan='+(r.has_significant?'ya':'tidak')
    +'; sampel fwd='+(r.forward_samples==null?'-':r.forward_samples)
    +'; trade cukup='+(r.trade_sufficient?'ya':'tidak')
    +'; timeout-dominated='+(r.timeout_dominated?'ya':'tidak');
  const map={
    'terbukti':'<span class="v-up" title="'+tip+'">terbukti</span>',
    'belum_pasti':'<span class="v-muted" title="'+tip+'">belum pasti</span>',
    'sampel_kurang':'<span class="v-red" title="'+tip+'">sampel kurang</span>',
    'tidak_ada_edge':'<span style="color:#8a9a90" title="'+tip+'">tanpa edge</span>'
  };
  return map[lvl]||'<span class="v-muted" title="'+tip+'">&mdash;</span>';
}
function acBandVerdictHtml(band){
  const b=(band&&typeof band==='object')?band:null;
  if(!b||!b.level||!b.n_horizons) return '<span class="v-muted">&mdash;</span>';
  const map={
    'terbukti':'<span class="v-up">terbukti</span>',
    'belum_pasti':'<span class="v-muted">belum pasti</span>',
    'sampel_kurang':'<span class="v-red">sampel kurang</span>',
    'tidak_ada_edge':'<span style="color:#8a9a90">tanpa edge</span>'
  };
  const lbl=map[b.level]||'<span class="v-muted">&mdash;</span>';
  return '<span class="v-white">Band harian–3 mingguan:</span> '+lbl
    +' <span class="v-muted" style="font-size:11px">('+b.n_terbukti+'/'+b.n_horizons
    +' horizon terbukti, '+b.n_significant_horizons+' signifikan)</span>';
}
async function runAccuracyMulti(t){
  const HS=[1,5,10,15];
  const r=await fetch(`/api/accuracy?ticker=${encodeURIComponent(t)}&horizons=${HS.join(",")}`);
  const d=await r.json(); if(d.error) throw new Error(d.error);
  const pct=(v)=> v==null?"-":(Number(v)*100).toFixed(1)+"%";
  const num=(v)=> v==null?"-":Number(v).toFixed(2);
  const minN=(d.min_n==null)?20:d.min_n;
  const rowsIn=(Array.isArray(d.rows)?d.rows:[]).slice(0,4);
  if(!rowsIn.length) throw new Error("Tidak ada data horizon");
  const hRows=rowsIn.map(row=>{
    try{
      const h=Number(row.horizon), f=row.forward||{}, tr=row.trade||{};
      const pf=tr.profit_factor==null?"~":num(tr.profit_factor);
      const rel=acReliabilityBadge(row.reliability);
      return '<tr><td style="text-align:left">'+acHorizonLabel(h)+'</td><td>'+h+'</td>'
        +'<td>'+pct(f.win_rate)+'</td>'
        +'<td class="'+((f.avg_ret==null||f.avg_ret>=0)?'v-up':'v-red')+'">'+num(f.avg_ret)+'%</td>'
        +'<td>'+(f.samples==null?'-':f.samples)+'</td>'
        +'<td>'+(tr.n_trades==null?'-':tr.n_trades)+'</td>'
        +'<td>'+pct(tr.win_rate)+'</td><td>'+pf+'</td><td>'+num(tr.avg_bars)+'</td>'
        +'<td>'+rel+'</td></tr>';
    }catch(err){ return ''; }
  }).filter(Boolean).join("");
  const stab=(Array.isArray(d.indicator_stability)?d.indicator_stability:[]);
  const verdict=acBandVerdictHtml(d.band_verdict);
  const stabRows=stab.slice(0,12).map(x=>'<tr>'
    +'<td style="text-align:left">'+(x.candidate?'<b>'+x.factor+'</b>':x.factor)+'</td>'
    +'<td>'+x.n_horizons+'</td><td>'+x.n_positive_edge+'</td><td>'+x.n_significant+'</td>'
    +'<td class="'+(x.avg_edge>=0?'v-up':'v-red')+'">'+(x.avg_edge>=0?'+':'')+pct(x.avg_edge)+'</td>'
    +'<td>'+(x.consistent?'<span class="v-up">konsisten</span>':'<span style="color:#8a9a90">&mdash;</span>')+'</td>'
    +'</tr>').join("") || '<tr><td colspan="6" style="text-align:center;color:#8a9a90">data kurang</td></tr>';
  $("#acResult").innerHTML=`
    <div class="grid">
      <div class="metric hl"><div class="k">Horizon Diuji</div><div class="v v-white">${rowsIn.length}</div></div>
      <div class="metric"><div class="k">Verdict Band</div><div class="v" style="font-size:12px;line-height:1.35">${verdict}</div></div>
      <div class="metric"><div class="k">Min Sampel/Trade</div><div class="v v-muted">${minN}</div></div>
      <div class="metric"><div class="k">Ticker</div><div class="v v-white">${d.ticker||t}</div></div>
    </div>
    <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Win-rate per horizon (Forward = arah return; Trade = populasi TP/SL, berbeda)</div>
    <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Horizon</th><th>Bar</th><th>Fwd WR</th><th>Fwd Avg</th><th>Fwd N</th><th>Trade N</th><th>Trade WR</th><th>PF</th><th>Avg Bar</th><th>Reliabilitas</th></tr></thead><tbody>${hRows}</tbody></table></div>
    <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Stabilitas indikator lintas horizon (edge forward titik per-indikator — beda konstruk dari verdict band di atas)</div>
    <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Indikator</th><th>Hadir</th><th>Edge&gt;0</th><th>Signifikan</th><th>Avg Edge</th><th>Konsisten Edge&gt;0</th></tr></thead><tbody>${stabRows}</tbody></table></div>
    <div class="mono" style="color:#8a9a90;font-size:10px;margin-top:10px">Reliabilitas per horizon: <b class="v-up">terbukti</b> = ada faktor signifikan &amp; sampel/trade cukup; <b class="v-muted">belum pasti</b> = sinyal ada tapi bukti belum kuat (mis. 1-bar timeout-dominated); <b class="v-red">sampel kurang</b> = sampel forward &lt; ${minN}; <b style="color:#8a9a90">tanpa edge</b> = sampel cukup tapi tak ada faktor signifikan. Verdict band (1–15 bar) = ringkasan reliabilitas: tanpa edge menveto; selain itu <b class="v-up">terbukti</b> bila ada horizon terbukti — horizon 1-bar yang timeout-dominated tidak memveto. Tabel stabilitas tetap <b>edge forward titik</b> per indikator (kolom "Konsisten Edge&gt;0"), jadi beda konstruk dari verdict band. Skor/rumus tidak diubah.</div>`;
}
async function runAccuracySingle(t){
    const r=await fetch(`/api/accuracy?ticker=${encodeURIComponent(t)}&horizon=${$("#acHorizon").value||10}`);
    const d=await r.json(); if(d.error) throw new Error(d.error);
    const pct=(v)=> v==null?"-":(Number(v)*100).toFixed(1)+"%";
    const num=(v)=> v==null?"-":Number(v).toFixed(2);
    const calRows=(d.calibration||[]).map(x=>'<tr><td style="text-align:left">'+x.bucket+'</td><td>'+x.n+'</td><td>'+pct(x.win_rate)+'</td><td>'+num(x.avg_ret)+'%</td><td class="'+(x.edge>=0?'v-up':'v-red')+'">'+(x.edge==null?'':(x.edge>=0?'+':'')+pct(x.edge))+'</td></tr>').join("");
    const agrRows=(d.agreement||[]).map(x=>'<tr><td style="text-align:left">'+x.bucket+'</td><td>'+x.n+'</td><td>'+pct(x.win_rate)+'</td><td>'+num(x.avg_ret)+'%</td></tr>').join("");
    const facRows=(d.factors||[]).map(x=>'<tr><td style="text-align:left">'+x.factor+'</td><td>'+x.n+'</td><td>'+pct(x.win_rate)+'</td><td>'+num(x.avg_ret)+'%</td><td class="'+(x.edge>=0?'v-up':'v-red')+'">'+(x.edge>=0?'+':'')+pct(x.edge)+'</td></tr>').join("");
    const relBadge=acReliabilityBadge(d.reliability);
    const minN=(d.min_n==null)?20:d.min_n;
    $("#acResult").innerHTML=`
      <div class="grid">
        <div class="metric hl"><div class="k">Base Win Rate</div><div class="v v-white">${pct(d.base_win_rate)}</div></div>
        <div class="metric"><div class="k">Base Avg Return</div><div class="v v-muted">${num(d.base_avg_ret)}%</div></div>
        <div class="metric"><div class="k">Sampel</div><div class="v v-white">${d.samples}</div></div>
        <div class="metric"><div class="k">Horizon</div><div class="v v-muted">${d.horizon} bar</div></div>
        <div class="metric"><div class="k">Reliabilitas</div><div class="v" style="font-size:12px;line-height:1.35">${relBadge}</div></div>
      </div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Kalibrasi Skor vs Hasil (${d.horizon} bar)</div>
      <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Bucket Skor</th><th>N</th><th>Win Rate</th><th>Avg Fwd Ret</th><th>Edge</th></tr></thead><tbody>${calRows}</tbody></table></div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Konfluensi: jumlah faktor setuju vs hasil</div>
      <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Faktor Setuju</th><th>N</th><th>Win Rate</th><th>Avg Fwd Ret</th></tr></thead><tbody>${agrRows}</tbody></table></div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Edge per Indikator (diurutkan)</div>
      <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Faktor</th><th>N</th><th>Win Rate</th><th>Avg Fwd Ret</th><th>Edge</th></tr></thead><tbody>${facRows}</tbody></table></div>
      <div class="mono" style="color:#8a9a90;font-size:10px;margin-top:10px">Reliabilitas horizon ini: <b class="v-up">terbukti</b> = ada faktor signifikan &amp; sampel/trade cukup; <b class="v-muted">belum pasti</b> = sinyal ada tapi bukti belum kuat (mis. timeout-dominated); <b class="v-red">sampel kurang</b> = sampel forward &lt; ${minN}; <b style="color:#8a9a90">tanpa edge</b> = sampel cukup tapi tak ada faktor signifikan. Edge titik mentah pada tabel di atas <b>bukan</b> bukti keandalan — baca verdict ini. Skor/rumus tidak diubah.</div>`;
}
$("#acRun").onclick = runAccuracy;
async function runAccuracy(){
  const t=($("#acTicker").value||"").trim().toUpperCase(); if(!t) return;
  const multi=!!(($("#acMulti")||{}).checked);
  showStatus(multi?"Mengukur akurasi lintas-horizon...":"Mengukur akurasi...", true); $("#acRun").disabled=true;
  try{
    if(multi){ await runAccuracyMulti(t); } else { await runAccuracySingle(t); }
    showStatus("Selesai");
  }catch(e){ $("#acResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ $("#acRun").disabled=false; }
}

/* ---------- Calibration: validate new indicator weights ---------- */
const cbRunEl = $("#cbRun");
if(cbRunEl) cbRunEl.onclick = runCalibrate;
async function runCalibrate(){
  const list = ($("#cbList")||{}).value || "lq45";
  const horizon = ($("#cbHorizon")||{}).value || 10;
  const minEdge = ($("#cbMinEdge")||{}).value || 0.03;
  showStatus("Mengkalibrasi indikator (" + list + ")...", true);
  if(cbRunEl) cbRunEl.disabled = true;
  try{
    const d = await (await fetch(`/api/calibrate?list=${encodeURIComponent(list)}&horizon=${horizon}&min_edge=${minEdge}`)).json();
    if(d.error) throw new Error(d.error);
    const pct = (v) => v==null?"-":(Number(v)*100).toFixed(1)+"%";
    const rows = (d.factors||[]).map(x=>'<tr><td style="text-align:left">'+(x.candidate?'<b style="color:var(--brand-dark)">'+x.factor+'</b>':x.factor)+'</td><td>'+x.n+'</td>'
      +'<td>'+pct(x.win_rate)+'</td><td class="'+(x.edge>=0?'v-up':'v-red')+'">'+(x.edge>=0?'+':'')+pct(x.edge)+'</td>'
      +'<td>'+(x.candidate?'<span class="mono">'+(x.edge>=Number(d.min_edge)?'kandidat ✓':'—')+'</span>':'<span class="mono" style="color:#8a9a90">inti</span>')+'</td></tr>').join("");
    const promo = (d.promoted||[]);
    const promoRows = promo.length ? promo.map(x=>'<tr><td style="text-align:left">'+x.factor+'</td><td class="v-up">+'+pct(x.edge)+'</td><td>'+(x.suggested_weight*100).toFixed(0)+'%</td></tr>').join("")
      : '<tr><td colspan="3" style="text-align:center;color:#8a9a90">Belum ada kandidat yang lolos ambang edge.</td></tr>';
    $("#cbResult").innerHTML = `
      <div class="grid">
        <div class="metric hl"><div class="k">Emiten diuji</div><div class="v v-white">${d.n_tickers}</div></div>
        <div class="metric"><div class="k">Base Win Rate</div><div class="v v-muted">${pct(d.base_win_rate)}</div></div>
        <div class="metric"><div class="k">Horizon</div><div class="v v-muted">${d.horizon} bar</div></div>
        <div class="metric"><div class="k">Ambang Edge</div><div class="v v-muted">+${pct(d.min_edge)}</div></div>
      </div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Usulan promosi ke skor (kandidat lolos)</div>
      <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Faktor</th><th>Edge</th><th>Bobot usulan</th></tr></thead><tbody>${promoRows}</tbody></table></div>
      <div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Edge semua faktor (dibobot sampel, ${d.n_tickers} emiten)</div>
      <div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Faktor</th><th>N</th><th>Win Rate</th><th>Edge</th><th>Jenis</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${(d.errors&&d.errors.length)?'<div class="mono" style="color:#ef5350;font-size:11px;margin-top:10px">'+d.errors.length+' emiten dilewati (data kurang).</div>':''}
      <div class="mono" style="color:#8a9a90;font-size:10px;margin-top:10px">Bobot usulan dipakai hanya setelah disetujui/dipromosikan — skor saat ini belum diubah.</div>`;
    showStatus("Selesai");
  }catch(e){ $("#cbResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ if(cbRunEl) cbRunEl.disabled=false; }
}

/* ---------- Edge per market regime ---------- */
const rgRunEl = $("#rgRun");
if(rgRunEl) rgRunEl.onclick = runRegimeEdge;
async function runRegimeEdge(){
  const list = ($("#rgList")||{}).value || "lq45";
  const horizon = ($("#rgHorizon")||{}).value || 10;
  showStatus("Menguji edge per regime...", true);
  if(rgRunEl) rgRunEl.disabled = true;
  try{
    const d = await (await fetch(`/api/regime-edge?list=${encodeURIComponent(list)}&horizon=${horizon}`)).json();
    if(d.error) throw new Error(d.error);
    const pct = (v)=> v==null?"-":(Number(v)*100).toFixed(1)+"%";
    const order = ["uptrend","ranging","downtrend"];
    let html = '<div class="grid">';
    order.forEach(r=>{ const g=(d.regimes||{})[r]||{}; html+='<div class="metric"><div class="k">'+r+'</div><div class="v v-muted">'+(g.base_win_rate==null?'-':pct(g.base_win_rate))+' <span style="color:#8a9a90;font-size:10px">n='+(g.n||0)+'</span></div></div>'; });
    html += '</div>';
    order.forEach(r=>{
      const g = (d.regimes||{})[r]||{};
      const rows = (g.factors||[]).slice(0,8).map(x=>'<tr><td style="text-align:left">'+(x.candidate?'<b>'+x.factor+'</b>':x.factor)+'</td><td>'+x.n+'</td><td>'+pct(x.win_rate)+'</td><td class="'+(x.edge>=0?'v-up':'v-red')+'">'+(x.edge>=0?'+':'')+pct(x.edge)+'</td></tr>').join("");
      html += '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">'+r+' (base '+(g.base_win_rate==null?'-':pct(g.base_win_rate))+')</div>'
        + '<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Faktor</th><th>N</th><th>WR</th><th>Edge</th></tr></thead><tbody>'+(rows||'<tr><td colspan="4" style="text-align:center;color:#8a9a90">data kurang</td></tr>')+'</tbody></table></div>';
    });
    html += '<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:10px">Terbaik saat IHSG uptrend; sinyal beli ditahan saat downtrend (regime filter).</div>';
    $("#rgResult").innerHTML = html;
    showStatus("Selesai");
  }catch(e){ $("#rgResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ if(rgRunEl) rgRunEl.disabled = false; }
}

/* ---------- Market news ---------- */
const mkNewsBtn = $("#mkNewsRun");
if(mkNewsBtn) mkNewsBtn.onclick = loadMarketNews;
async function loadMarketNews(){
  const el = $("#mkNewsResult"); if(!el) return;
  el.innerHTML = '<div class="empty sm">Memuat berita pasar...</div>';
  showStatus("Memuat berita pasar...", true);
  try{
    const n = await (await fetch('/api/news/market')).json();
    if(n.error) throw new Error(n.error);
    const cls = n.label==="Positif"?"v-up":(n.label==="Negatif"?"v-red":"v-muted");
    const items = newsCardsHtml(n.items||[]);
    el.innerHTML = '<div class="grid">'
      + '<div class="metric hl"><div class="k">Sentimen Pasar</div><div class="v '+cls+'">'+n.label+'</div></div>'
      + '<div class="metric"><div class="k">Skor rata-rata</div><div class="v v-muted">'+(n.avg_sentiment==null?"-":Number(n.avg_sentiment).toFixed(2))+'</div></div>'
      + '<div class="metric"><div class="k">Jumlah berita</div><div class="v v-white">'+n.count+'</div></div>'
      + '</div>'
      + (items ? '<div style="margin-top:12px">'+items+'</div>' : (n.degraded ? '<div class="empty sm">Gagal memuat berita pasar (sumber tidak tersedia).</div>' : '<div class="empty sm">Tidak ada berita pasar saat ini.</div>'));
    showStatus("Selesai");
  }catch(e){ el.innerHTML = '<div class="empty sm">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
}

/* ---------- Score optimization (walk-forward training) ---------- */
function renderModel(m){
  const el = $("#trResult"); if(!el || !m) return;
  const pct = (v)=> v==null?"-":(Number(v)*100).toFixed(1)+"%";
  const cw = m.component_weights || {};
  const ccoef = m.component_coef || {};
  const cwRows = Object.keys(cw).map(k=>{
    const c = ccoef[k];
    const cls = (c==null) ? "" : (c>=0 ? "v-up" : "v-red");
    const sign = (c==null) ? "" : (c>=0 ? "+" : "");
    return '<div class="check" style="justify-content:space-between"><span>'+k+'</span><span class="mono">'+Number(cw[k]).toFixed(1)+'% <span class="'+cls+'">('+sign+(c==null?"-":Number(c).toFixed(2))+')</span></span></div>';
  }).join('');
  const ok = m.edge_ok;
  const status = ok
    ? '<span class="v-up">AKTIF — skor live memakai blend ML</span>'
    : '<span class="v-red">TIDAK LULUS OOS — skor tetap heuristik</span>';
  const foldAuc = (m.folds_auc||[]).join(" / ");
  el.innerHTML = '<div class="grid">'
    + '<div class="metric hl"><div class="k">AUC OOS (rata-rata fold)</div><div class="v '+(ok?'v-up':'v-red')+'">'+(m.auc==null?'-':Number(m.auc).toFixed(3))+'</div></div>'
    + '<div class="metric"><div class="k">Ambang AUC</div><div class="v v-muted">'+Number(m.min_oos_auc!=null?m.min_oos_auc:0.53).toFixed(2)+'</div></div>'
    + '<div class="metric"><div class="k">Balanced Acc</div><div class="v v-muted">'+pct(m.balanced_accuracy)+'</div></div>'
    + '<div class="metric"><div class="k">Akurasi / Base</div><div class="v v-muted">'+pct(m.oos_accuracy)+' / '+pct(m.base_rate)+'</div></div>'
    + '<div class="metric"><div class="k">Sampel / Emiten</div><div class="v v-muted">'+m.n_samples+' / '+m.n_tickers+'</div></div>'
    + '<div class="metric"><div class="k">Dilatih</div><div class="v v-muted" style="font-size:12px">'+m.trained_at+'</div></div>'
    + '</div>'
    + '<div class="mono" style="margin-top:12px;font-size:12px">Status: '+status+'</div>'
    + '<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:4px">AUC per fold: '+foldAuc+'</div>'
    + '<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:18px 0 8px">Bobot komponen (importance % &amp; koefisien arah)</div>'
    + '<div class="checks" style="grid-template-columns:1fr 1fr">'+cwRows+'</div>'
    + '<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:8px">Alpha ML '+m.alpha+' (efektif '+m.effective_alpha+') &middot; horizon '+m.horizon+' &middot; '+m.folds+' folds</div>';
}
async function loadModelStatus(){
  const el = $("#trResult"); if(!el) return;
  try{
    const d = await (await fetch('/api/model')).json();
    if(!d.available){ el.innerHTML = '<div class="empty">Belum ada model. Tekan Latih &amp; Optimalkan (butuh ~30-60 dtk).</div>'; return; }
    renderModel(d.model);
  }catch(e){ el.innerHTML = '<div class="empty">Gagal memuat status model.</div>'; }
}
const trRunEl = $("#trRun");
if(trRunEl) trRunEl.onclick = runTrain;
async function runTrain(){
  const list = ($("#trList")||{}).value || "idx30";
  const horizon = ($("#trHorizon")||{}).value || 10;
  const folds = ($("#trFolds")||{}).value || 5;
  const alpha = ($("#trAlpha")||{}).value || 0.5;
  showStatus("Melatih model skor (walk-forward)... bisa 30-60 dtk", true);
  if(trRunEl) trRunEl.disabled = true;
  try{
    const d = await (await fetch(`/api/train?list=${encodeURIComponent(list)}&horizon=${horizon}&folds=${folds}&alpha=${alpha}`)).json();
    if(d.error) throw new Error(d.error);
    renderModel(d.model);
    showStatus("Model skor terlatih");
    if(typeof analyze === "function") analyze(true);
  }catch(e){ $("#trResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ if(trRunEl) trRunEl.disabled=false; }
}
const mdStatusBtnEl = $("#mdStatusBtn");
if(mdStatusBtnEl) mdStatusBtnEl.onclick = loadModelStatus;
loadModelStatus();


/* ---------- A/B comparison: legacy vs decision engine ---------- */
function abMetricsTable(leg, dec){
  const pct = (v)=> v==null?"-":(Number(v)*100).toFixed(1)+"%";
  const num = (v)=> v==null?"-":Number(v).toFixed(2);
  const row = (label, a, b, inv)=>{
    let clsA="", clsB="";
    if(a!=null && b!=null){
      const better = inv ? (b<a) : (b>a);
      clsB = better ? "v-up" : "v-red";
    }
    return '<tr><td style="text-align:left">'+label+'</td><td class="'+clsA+'">'+a+'</td><td class="'+clsB+'">'+b+'</td></tr>';
  };
  const decP = dec.profit_factor==null?"~":num(dec.profit_factor);
  const legP = leg.profit_factor==null?"~":num(leg.profit_factor);
  return '<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">Metrik</th><th>Legacy</th><th>Decision</th></tr></thead><tbody>'
    + row('Jumlah Trade', leg.n_trades, dec.n_trades, false)
    + row('Win Rate', pct(leg.win_rate), pct(dec.win_rate), false)
    + row('Profit Factor', legP, decP, false)
    + row('Expectancy %', num(leg.expectancy_pct!=null?leg.expectancy_pct:(leg.expectancy||0)*100), num(dec.expectancy_pct!=null?dec.expectancy_pct:(dec.expectancy||0)*100), false)
    + row('Avg Return %', num(leg.avg_return_pct!=null?leg.avg_return_pct:(leg.total_return||0)*100), num(dec.avg_return_pct!=null?dec.avg_return_pct:(dec.total_return||0)*100), false)
    + row('Max DD %', num(leg.avg_max_dd_pct!=null?leg.avg_max_dd_pct:(leg.max_drawdown||0)*100), num(dec.avg_max_dd_pct!=null?dec.avg_max_dd_pct:(dec.max_drawdown||0)*100), true)
    + row('Avg R', num(leg.avg_r), num(dec.avg_r), false)
    + row('Median R', num(leg.median_r), num(dec.median_r), false)
    + row('Max Consec Loss', leg.max_consec_losses, dec.max_consec_losses, true)
    + row('TP rate', pct(leg.tp_rate), pct(dec.tp_rate), false)
    + row('SL rate', pct(leg.sl_rate), pct(dec.sl_rate), true)
    + row('Avg bars', num(leg.avg_bars), num(dec.avg_bars), true)
    + '</tbody></table></div>';
}
const btABEl = $("#btAB");
if(btABEl) btABEl.onclick = async function(){
  const t=($("#btTicker").value||"").trim().toUpperCase(); if(!t) return;
  showStatus("A/B backtest "+t+"...", true); btABEl.disabled=true;
  try{
    const d=await (await fetch(`/api/compare-backtest?ticker=${encodeURIComponent(t)}&tp_rr=${$("#btTp").value}&sl_mult=${$("#btSl").value}&max_hold=${$("#btHold").value}`)).json();
    if(d.error) throw new Error(d.error);
    $("#abResult").innerHTML='<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px">A/B '+d.ticker+' (parameter sama)</div>'+abMetricsTable(d.legacy,d.decision)
      +'<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:8px">Decision = structure + regime + filter no-trade. Jangan menilai dari satu emiten.</div>';
    showStatus("Selesai");
  }catch(e){ $("#abResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ btABEl.disabled=false; }
};
const btABUEl = $("#btABU");
if(btABUEl) btABUEl.onclick = async function(){
  const list=($("#abList")||{}).value||"idx30";
  showStatus("A/B universe "+list+"... (~30-60 dtk)", true); btABUEl.disabled=true;
  try{
    const d=await (await fetch(`/api/compare-universe?list=${encodeURIComponent(list)}&tp_rr=${$("#btTp")?$("#btTp").value:3}&sl_mult=${$("#btSl")?$("#btSl").value:2}&max_hold=${$("#btHold")?$("#btHold").value:20}`)).json();
    if(d.error) throw new Error(d.error);
    $("#abuResult").innerHTML='<div class="mono" style="color:#525252;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px">A/B Universe '+list+' ('+d.n_tickers+' emiten, agregat)</div>'+abMetricsTable(d.legacy,d.decision)
      +'<div class="mono" style="color:#8a9a90;font-size:10px;margin-top:8px">Agregat lintas emiten: patokan robustness, bukan win-rate semata.</div>';
    showStatus("Selesai");
  }catch(e){ $("#abuResult").innerHTML='<div class="empty">Gagal: '+e.message+'</div>'; showStatus("Gagal"); }
  finally{ btABUEl.disabled=false; }
};
