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
