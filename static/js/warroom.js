// Kontrol + chat War Room dari HP. Tanpa dependensi; CSP-safe (tanpa inline handler).
(function () {
  "use strict";

  var KEY_STORAGE = "laum_warroom_key";
  var REFRESH_MS = 5000;
  // Event teknis yang disembunyikan dari tampilan biasa (toggle "detail teknis").
  var NOISE_CATEGORIES = { budget: 1, agent: 1 };

  var el = function (id) { return document.getElementById(id); };

  var keyInput = el("api-key");
  var activity = el("activity");
  var activityText = el("activity-text");
  var activitySub = el("activity-sub");
  var stateBadge = el("state-badge");
  var iteration = el("iteration");
  var budget = el("budget");
  var backlog = el("backlog");
  var eventsList = el("events-list");
  var evDetail = el("ev-detail");
  var voice = el("voice");
  var voiceCount = el("voice-count");
  var topic = el("topic");
  var toast = el("toast");

  var btnPause = el("btn-pause");
  var btnResume = el("btn-resume");
  var btnStop = el("btn-stop");
  var btnLoop = el("btn-loop");
  var btnLoops = el("btn-loops");
  var btnDiscuss = el("btn-discuss");

  var chatAgent = el("chat-agent");
  var chatLog = el("chat-log");
  var chatInput = el("chat-input");
  var chatSend = el("chat-send");
  var chatClear = el("chat-clear");

  var chatSessions = {};
  var lastData = null;

  function currentKey() {
    var v = keyInput.value.trim();
    try { localStorage.setItem(KEY_STORAGE, v); } catch (e) { /* abaikan */ }
    return v;
  }

  function apiKeyHeader() {
    var k = currentKey();
    return k ? { "X-API-Key": k } : {};
  }

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () { toast.classList.remove("show"); }, 2800);
  }

  function fmtIDR(n) {
    if (n === null || n === undefined) { return "-"; }
    return Number(n).toLocaleString("id-ID", { maximumFractionDigits: 0 });
  }

  function fmtAge(s) {
    if (s === null || s === undefined) { return "-"; }
    if (s < 60) { return s + "s lalu"; }
    if (s < 3600) { return Math.floor(s / 60) + "m lalu"; }
    return Math.floor(s / 3600) + "j lalu";
  }

  function badgeClass(mode) {
    if (mode === "normal") { return "green"; }
    if (mode === "warning" || mode === "reduced") { return "yellow"; }
    if (mode === "paused") { return "red"; }
    return "gray";
  }

  function setButtonsBusy(flag) {
    [btnPause, btnResume, btnStop, btnLoop, btnLoops, btnDiscuss].forEach(function (b) { b.disabled = flag; });
  }

  function renderActivity(d) {
    var st = d.state || {};
    var act = d.activity || {};
    activity.className = "live " + (act.running ? "on" : "off") + (act.kind === "rapat" ? " k-rapat" : "");
    activityText.textContent = act.label || (act.running ? "AKTIF" : "DIAM");
    var parts = [st.state || "-"];
    if (act.warroomProcs) { parts.push(act.warroomProcs + " proses"); }
    parts.push("aktivitas " + fmtAge(act.lastEventAgeSec));
    activitySub.textContent = parts.join(" · ");
  }

  function renderVoice(d) {
    var list = (d.voice || []).slice().reverse();  // terbaru di atas
    voice.replaceChildren();
    voiceCount.textContent = list.length ? "(" + list.length + " terakhir)" : "";
    if (!list.length) {
      var m = document.createElement("div"); m.className = "muted";
      m.textContent = "Belum ada aktivitas agen.";
      voice.appendChild(m);
      return;
    }
    list.forEach(function (v) {
      var div = document.createElement("div"); div.className = "voiceline";
      var who = document.createElement("span"); who.className = "who";
      who.textContent = (v.agent || "?") + " ";
      var ph = document.createElement("span"); ph.className = "ph";
      ph.textContent = v.phase ? "(" + v.phase + ") " : "";
      var tx = document.createElement("span");
      tx.textContent = v.text || "";
      div.appendChild(who); div.appendChild(ph); div.appendChild(tx);
      voice.appendChild(div);
    });
  }

  function renderEvents(d) {
    var ev = d.events || [];
    var detail = evDetail.checked;
    var shown = ev.filter(function (e) { return detail || !NOISE_CATEGORIES[e.category]; }).slice().reverse().slice(0, 12);
    eventsList.replaceChildren();
    if (!shown.length) {
      var q = document.createElement("div"); q.className = "muted";
      q.textContent = ev.length ? "(hanya event teknis — centang 'detail teknis')" : "Belum ada.";
      eventsList.appendChild(q);
      return;
    }
    shown.forEach(function (e) {
      var div = document.createElement("div"); div.className = "ev";
      var ts = document.createElement("span"); ts.className = "ts";
      ts.textContent = (e.ts || "").replace("T", " ").slice(0, 19) + " ";
      var msg = document.createElement("span");
      msg.textContent = (e.actor ? e.actor + ": " : "") + (e.message || "");
      div.appendChild(ts); div.appendChild(msg);
      eventsList.appendChild(div);
    });
  }

  function renderStatus(d) {
    var st = d.state || {};
    var ctl = d.control || {};
    var b = d.budget || {};
    var bl = d.backlog || {};
    var state = st.state || "STOPPED";
    stateBadge.textContent = state + (ctl.pauseRequested ? " · jeda diminta" : "") + (ctl.stopRequested ? " · stop diminta" : "");
    stateBadge.className = "badge " + badgeClass(b.mode || "normal");
    iteration.textContent = "iterasi #" + (st.iteration || 0) + " · sukses #" + (st.lastSuccessIteration || 0);

    budget.replaceChildren();
    [["Mode", (b.mode || "-")],
     ["Terpakai", "Rp" + fmtIDR(b.spentIDR)],
     ["Cadangan", "Rp" + fmtIDR(b.reservedIDR)],
     ["Sisa", "Rp" + fmtIDR(b.remainingIDR)],
     ["Ledger", b.ledgerHealthy ? "sehat" : "RUSAK"]].forEach(function (row) {
      var k = document.createElement("div"); k.className = "k"; k.textContent = row[0];
      var v = document.createElement("div"); v.className = "v"; v.textContent = row[1];
      budget.appendChild(k); budget.appendChild(v);
    });

    backlog.replaceChildren();
    var h2 = document.createElement("h2"); h2.textContent = "Backlog (" + (bl.total || 0) + ")";
    backlog.appendChild(h2);
    var nxt = bl.next;
    if (nxt) {
      var p = document.createElement("div");
      p.textContent = nxt.id + " [" + (nxt.severity || "-") + "] " + (nxt.title || "");
      backlog.appendChild(p);
    } else {
      var q = document.createElement("div"); q.className = "muted"; q.textContent = "Tidak ada item terbuka.";
      backlog.appendChild(q);
    }
  }

  function refresh() {
    fetch("/api/warroom/status", { headers: apiKeyHeader() })
      .then(function (r) {
        if (!r.ok) {
          if (r.status === 401) { throw new Error("Kunci salah"); }
          throw new Error("Status gagal (" + r.status + ")");
        }
        return r.json();
      })
      .then(function (d) {
        lastData = d;
        renderActivity(d); renderVoice(d); renderStatus(d); renderEvents(d);
      })
      .catch(function (e) { showToast(e.message); });
  }

  function post(url, body) {
    setButtonsBusy(true);
    fetch(url, {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, apiKeyHeader()),
      body: JSON.stringify(body || {})
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) { throw new Error(j.error || ("Gagal (" + r.status + ")")); }
          return j;
        });
      })
      .then(function (j) {
        showToast(j.ok === false ? (j.error || "Ditolak") : "OK");
        refresh();
      })
      .catch(function (e) { showToast(e.message); })
      .finally(function () { setButtonsBusy(false); });
  }

  function addMsg(cls, text) {
    var div = document.createElement("div");
    div.className = "msg " + cls;
    div.textContent = text;
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
    return div;
  }

  function sendChat() {
    var agent = chatAgent.value;
    var text = chatInput.value.trim();
    if (!text) { return; }
    addMsg("me", text);
    chatInput.value = "";
    chatSend.disabled = true;
    var typing = addMsg("bot", "… mengetik (" + agent + ")");
    fetch("/api/warroom/chat", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, apiKeyHeader()),
      body: JSON.stringify({ agent: agent, message: text, session: chatSessions[agent] || "" })
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) { throw new Error(j.error || ("Gagal (" + r.status + ")")); }
          return j;
        });
      })
      .then(function (j) {
        if (j.session) { chatSessions[agent] = j.session; }
        typing.className = "msg bot";
        typing.textContent = j.reply || "(balasan kosong)";
        if (!j.ok && j.reason) { addMsg("sys", "catatan: " + j.reason); }
        refresh();
      })
      .catch(function (e) {
        typing.className = "msg sys";
        typing.textContent = "gagal: " + e.message;
      })
      .finally(function () {
        chatSend.disabled = false;
        chatInput.focus();
        chatLog.scrollTop = chatLog.scrollHeight;
      });
  }

  btnPause.addEventListener("click", function () { post("/api/warroom/control", { action: "pause" }); });
  btnResume.addEventListener("click", function () { post("/api/warroom/control", { action: "resume" }); });
  btnStop.addEventListener("click", function () { post("/api/warroom/control", { action: "stop" }); });
  btnLoop.addEventListener("click", function () { post("/api/warroom/loop", {}); });
  btnLoops.addEventListener("click", function () {
    if (!window.confirm("Loop SELAMANYA akan jalan terus memakai token/anggaran sampai habis. Lanjutkan?")) { return; }
    post("/api/warroom/loop", { forever: true });
  });
  btnDiscuss.addEventListener("click", function () {
    var t = topic.value.trim();
    if (!t) { showToast("Isi topik dulu"); return; }
    post("/api/warroom/discuss", { topic: t });
  });
  keyInput.addEventListener("change", currentKey);
  evDetail.addEventListener("change", function () { if (lastData) { renderEvents(lastData); } });

  chatSend.addEventListener("click", sendChat);
  chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  chatClear.addEventListener("click", function () {
    chatLog.replaceChildren();
    delete chatSessions[chatAgent.value];
    addMsg("sys", "Percakapan dibersihkan.");
  });

  try { keyInput.value = localStorage.getItem(KEY_STORAGE) || ""; } catch (e) { /* abaikan */ }

  addMsg("sys", "Pilih agen lalu kirim pesan. Balasan muncul di sini.");
  refresh();
  setInterval(refresh, REFRESH_MS);
})();
