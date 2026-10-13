"""Endpoint War Room: panel kontrol jarak jauh (HP via Tailscale).

Membaca status dari berkas state War Room (``tools/warroom/state/``) lewat
skrip PowerShell read-only ``Get-WarRoomStatusJson.ps1`` dan menulis kendali
(pause/resume/stop) ke ``control.json`` — memakai kembali logika yang sudah
ada di sisi PowerShell, tanpa menyalin rumus anggaran/prioritas ke Python.

Keamanan: seluruh rute ``/api/warroom/*`` mewajibkan header ``X-API-Key``
bila ``API_KEY`` diset (fail-open dengan warning bila kosong). Tindakan
loop/rapat dijalankan sebagai proses PowerShell lepas (detached) sehingga
bertahan setelah respons HTTP selesai.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

import state
from routes._util import json_object

bp = Blueprint("warroom", __name__)

_ROOT = Path(__file__).resolve().parent.parent
_TOOL_DIR = _ROOT / "tools" / "warroom"

# Bendera Windows agar proses anak hidup tanpa jendela. CATATAN: DETACHED_PROCESS
# (0x00000008) TIDAK dipakai — di sistem ini proses lahir tetapi tidak menjalankan
# apa pun (terbukti lewat uji). CREATE_NO_WINDOW + CREATE_NEW_PROCESS_GROUP bekerja
# dan proses tetap hidup walau Flask ditutup.
_NEW_GROUP = 0x00000200  # CREATE_NEW_PROCESS_GROUP
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

_ACTIVE_STATES = {
    "STARTING", "OBSERVING", "INVESTIGATING", "PLANNING",
    "IMPLEMENTING", "TESTING", "REVIEWING", "RECORDING", "OBSERVING_AGAIN",
    "PAUSED",
}

_ALLOWED_CONTROL = {"pause", "resume", "stop"}

# Alias ramah untuk chat -> nama agen OpenCode (sama dengan konfigurasi War Room).
_CHAT_ALIASES = {
    "lead": "lead-engineer",
    "code": "code-engineer",
    "quant": "quant-analyst",
    "qa": "qa-engineer",
    "reviewer": "reviewer",
    "security": "security-engineer",
    "uiux": "uiux-designer",
    "tech": "technical-analyst",
    "technical": "technical-analyst",
    "fundamental": "fundamental-analyst",
    "seo": "seo-engineer",
}


def _state_dir() -> Path:
    return Path(os.environ.get("WARROOM_STATE_DIR") or (_TOOL_DIR / "state"))


def _powershell() -> str:
    return shutil.which("powershell.exe") or "powershell.exe"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_key_ok() -> bool:
    key = state.api_key()
    if not key:
        return True  # API_KEY tidak diset -> fail-open (warning dicetak di webapp)
    return request.headers.get("X-API-Key") == key


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _append_event(category: str, message: str, level: str = "info") -> None:
    line = json.dumps(
        {
            "ts": _now_utc(),
            "level": level,
            "category": category,
            "actor": "web",
            "message": message,
            "data": None,
        },
        ensure_ascii=False,
    )
    path = _state_dir() / "events.jsonl"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _set_control(action: str) -> dict:
    cf = _state_dir() / "control.json"
    cur = _read_json(cf, {"pauseRequested": False, "stopRequested": False})
    pause = bool(cur.get("pauseRequested"))
    stop = bool(cur.get("stopRequested"))
    if action == "pause":
        pause = True
    elif action == "resume":
        pause = False
        stop = False
    elif action == "stop":
        stop = True
        pause = False
    obj = {
        "pauseRequested": pause,
        "stopRequested": stop,
        "updatedAt": _now_utc(),
        "by": "web",
    }
    _write_json(cf, obj)
    _append_event("orchestrator", f"control web: {action}")
    return obj


def _run_status() -> tuple[dict | None, str]:
    script = _TOOL_DIR / "Get-WarRoomStatusJson.ps1"
    if not script.exists():
        return None, "skrip status tidak ditemukan"
    try:
        proc = subprocess.run(
            [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(script)],
            cwd=str(_ROOT),
            capture_output=True,
            timeout=45,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"gagal menjalankan status: {exc}"
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout or "status gagal").strip()[-500:]
    try:
        return json.loads(proc.stdout), ""
    except ValueError as exc:
        return None, f"JSON status tak terbaca: {exc}"


def _spawn_detached(args: list[str]) -> None:
    subprocess.Popen(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass"] + args,
        cwd=str(_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=_NEW_GROUP | _NO_WINDOW,
    )


def _loop_running(data: dict) -> bool:
    st = data.get("state") or {}
    return st.get("state", "STOPPED") in _ACTIVE_STATES


@bp.before_request
def _guard():
    if request.path.startswith("/api/warroom") and not _api_key_ok():
        return jsonify(error="Unauthorized"), 401
    return None


@bp.route("/warroom")
def page():
    return render_template("warroom.html")


@bp.route("/api/warroom/status")
def api_status():
    data, err = _run_status()
    if err:
        return jsonify(error=err), 502
    return jsonify(data)


@bp.route("/api/warroom/control", methods=["POST"])
def api_control():
    body = json_object()
    if body is None:
        return jsonify(error="Body harus objek JSON"), 400
    action = (body.get("action") or "").strip().lower()
    if action not in _ALLOWED_CONTROL:
        return jsonify(error="action harus pause|resume|stop"), 400
    return jsonify(ok=True, control=_set_control(action))


@bp.route("/api/warroom/loop", methods=["POST"])
def api_loop():
    body = json_object()
    if body is None:
        return jsonify(error="Body harus objek JSON"), 400
    forever = bool(body.get("forever"))
    data, err = _run_status()
    if err:
        return jsonify(error=err), 502
    if _loop_running(data or {}):
        return jsonify(ok=False, error="loop sudah berjalan"), 409
    _set_control("resume")  # stop/pause yang tertinggal jangan memblokir run baru
    args = ["-File", str(_TOOL_DIR / "Invoke-AutonomousLoop.ps1")]
    if forever:
        args += ["-Forever", "-Fast"]
    _spawn_detached(args)
    _append_event("orchestrator", "loop diluncurkan dari web" + (" (SELAMANYA)" if forever else ""))
    return jsonify(ok=True, forever=forever)


@bp.route("/api/warroom/discuss", methods=["POST"])
def api_discuss():
    body = json_object()
    if body is None:
        return jsonify(error="Body harus objek JSON"), 400
    topic = (body.get("topic") or "").strip()
    if not topic:
        return jsonify(error="topic wajib diisi"), 400
    if len(topic) > 500 or any(ord(c) < 0x20 for c in topic):
        return jsonify(error="topic terlalu panjang / memuat karakter kontrol"), 400
    _set_control("resume")  # pastikan rapat tidak langsung terblokir stop lama
    _spawn_detached([
        "-File", str(_TOOL_DIR / "Start-WarRoom.ps1"),
        "-Command", f"discuss {topic}",
    ])
    _append_event("orchestrator", f"rapat diluncurkan dari web: {topic[:80]}")
    return jsonify(ok=True)


@bp.route("/api/warroom/chat", methods=["POST"])
def api_chat():
    """Chat interaktif satu agen: satu pesan -> satu balasan (kendali anggaran).

    Sesi OpenCode diteruskan lewat ``session`` agar percakapan berlanjut (konteks
    tetap). Balasan dikembalikan di body; proses berat ini memang butuh waktu,
    jadi UI menampilkan indikator "mengetik" selama menunggu.
    """
    body = json_object()
    if body is None:
        return jsonify(error="Body harus objek JSON"), 400
    agent = (body.get("agent") or "lead").strip().lower()
    agent = _CHAT_ALIASES.get(agent, agent)
    message = body.get("message") or ""
    if not message.strip():
        return jsonify(error="pesan kosong"), 400
    if len(message) > 4000 or any(ord(c) < 0x20 and c not in "\n\t" for c in message):
        return jsonify(error="pesan terlalu panjang / memuat karakter kontrol"), 400
    session = (body.get("session") or "").strip()

    task = _TOOL_DIR / "Invoke-WarRoomTask.ps1"
    if not task.exists():
        return jsonify(error="skrip tugas tidak ditemukan"), 500
    cmd = [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(task),
           "-Agent", agent, "-Prompt", message.strip(),
           "-CycleId", "web-chat", "-Role", "chat"]
    if session:
        cmd += ["-SessionId", session]
    try:
        proc = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True,
                              timeout=300, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return jsonify(error=f"gagal menjalankan agen: {exc}"), 504

    reply = None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                reply = json.loads(line)
                break
            except ValueError:
                continue
    if reply is None:
        detail = (proc.stderr or proc.stdout or "tanpa keluaran").strip()[-500:]
        return jsonify(error="agen tidak mengembalikan hasil", detail=detail), 502
    return jsonify(
        ok=bool(reply.get("ok")),
        agent=reply.get("agent") or agent,
        reply=reply.get("text") or "",
        session=reply.get("sessionId") or session,
        costIDR=reply.get("costIDR"),
        reason=reply.get("reason") or reply.get("error") or "",
    )
