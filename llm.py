from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

PROMPT_PATH = Path("gemini-code-1791271032904.md")
CFG_PATH = Path("llm.json")


def _cfg() -> dict:
    if CFG_PATH.exists():
        try:
            data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def configured() -> bool:
    return bool(_key())


def _key() -> str:
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY") or str(_cfg().get("api_key") or "")


def _base() -> str:
    base = (os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL")
            or _cfg().get("base_url") or "https://api.openai.com/v1")
    return str(base).rstrip("/")


def _model() -> str:
    return os.environ.get("LLM_MODEL") or str(_cfg().get("model") or "deepseek-reasoner")


def load_prompt() -> str:
    """System prompt diambil dari file MD (jika ada), fallback ke prompt bawaan."""
    if PROMPT_PATH.exists():
        try:
            text = PROMPT_PATH.read_text(encoding="utf-8")
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) == 3:
                    text = parts[2]
            return text.strip()
        except Exception:
            pass
    return (
        "Kamu adalah Multi-Agent Consensus System untuk analisis saham IHSG: @technical, "
        "@bandarmologi, @fundamental, @sentiment, dan @risk_moderator yang punya hak veto."
    )


def chat(system: str, user: str, timeout: float = 90.0) -> str:
    if not configured():
        raise RuntimeError("LLM belum dikonfigurasi (set OPENAI_API_KEY / LLM_API_KEY)")
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        _base() + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + _key()},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "ignore"))
    return data["choices"][0]["message"]["content"]
