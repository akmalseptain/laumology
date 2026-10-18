from __future__ import annotations

import json
import os
import urllib.request


def _env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v.strip()
    return ""


def webhook_url() -> str:
    return _env("IDX_ALERT_WEBHOOK")


def send_webhook(url: str, payload: dict) -> dict:
    if not url:
        return {"ok": False, "reason": "no_webhook"}
    try:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return {"ok": True, "status": resp.status}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def dispatch(text: str, payload: dict | None = None) -> dict:
    """Forward an alert to an optional webhook (set IDX_ALERT_WEBHOOK)."""
    hook = webhook_url()
    if not hook:
        return {"webhook": {"ok": False, "reason": "not_configured"}}
    return {"webhook": send_webhook(hook, payload or {"text": text})}


def signal_alert(row: dict) -> dict:
    """Kirim satu sinyal sebagai alert terstruktur ke webhook (opsional).

    ``row`` adalah dict sinyal ala baris DB (ticker, signal, action, score,
    confidence, grade, price, entry, stop_loss, tp1, source, ts). Payload
    dikirim sebagai field terstruktur supaya penerima (bot/relay) bisa
    memformat sendiri, bukan cuma teks yang sudah dirangkai.
    """
    def _num(v):
        return None if v is None else float(v)

    payload = {
        "type": "signal",
        "ticker": row.get("ticker"),
        "signal": row.get("signal"),
        "action": row.get("action"),
        "score": row.get("score"),
        "confidence": row.get("confidence"),
        "grade": row.get("grade"),
        "price": _num(row.get("price")),
        "entry": _num(row.get("entry")),
        "stop_loss": _num(row.get("stop_loss")),
        "tp1": _num(row.get("tp1")),
        "source": row.get("source"),
        "ts": row.get("ts"),
    }
    def _fmt(v):
        # Field harga bisa absen (mis. sinyal manual): tampilkan "n/a", jangan crash.
        return "n/a" if v is None else f"{v:,.0f}"

    text = (
        f"[{payload['signal']}] {payload['ticker']} | skor {payload['score']} "
        f"conf {payload['confidence']}% | harga {_fmt(payload['price'])} "
        f"| SL {_fmt(payload['stop_loss'])} TP1 {_fmt(payload['tp1'])}"
    )
    return dispatch(text, payload)
