from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

PROMPT_PATH = Path("gemini-code-1791271032904.md")
CFG_PATH = Path("llm.json")

# Hanya nama berkas prompt yang aman dipakai/diekspos (cegah `.env`, `llm.json`,
# atau path absolut bocor lewat /api/llm/status).
_ALLOWED_PROMPT_SUFFIXES = (".md", ".txt")


def _prompt_path() -> Path:
    """Path prompt aktif; env ``LLM_PROMPT_PATH`` dibaca lazily agar dapat diuji."""
    raw = os.environ.get("LLM_PROMPT_PATH")
    return Path(raw) if raw else PROMPT_PATH


def _is_safe_prompt_name(name: str) -> bool:
    return bool(name) and not name.startswith(".") and name.lower().endswith(_ALLOWED_PROMPT_SUFFIXES)


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
    # Default diselaraskan dengan default model (deepseek-reasoner) dan
    # .env.example / llm.example.json agar tidak mengarah ke endpoint OpenAI.
    base = (os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL")
            or _cfg().get("base_url") or "https://api.deepseek.com/v1")
    return str(base).rstrip("/")


def _model() -> str:
    return os.environ.get("LLM_MODEL") or str(_cfg().get("model") or "deepseek-reasoner")


def load_prompt() -> str:
    """System prompt diambil dari file MD (jika ada), fallback ke prompt bawaan."""
    path = _prompt_path()
    if _is_safe_prompt_name(path.name) and path.exists():
        try:
            text = path.read_text(encoding="utf-8")
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


def prompt_info() -> dict:
    """Info prompt aktif tanpa membocorkan path absolut/rahasia.

    Kembalikan ``{"file": <basename|null>, "source": "file"|"default"}``.
    """
    try:
        path = _prompt_path()
        name = path.name
        if _is_safe_prompt_name(name) and path.exists():
            return {"file": name, "source": "file"}
    except Exception:
        pass
    return {"file": None, "source": "default"}


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
