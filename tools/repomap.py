"""Peta repo ringkas (ala aider repomap): daftar simbol tingkat-atas per berkas .py.

Dipakai War Room untuk memberi konteks ringkas ke agen (hemat token, lebih tepat).
Jalankan: py -3.14 tools/repomap.py [--max N]
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", ".cache", "output", "__pycache__", ".venv", "venv",
    "node_modules", "Sciencebasedlifter", "state", "tools", "tests",
}


def _entries(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"  def {node.name}")
        elif isinstance(node, ast.ClassDef):
            out.append(f"  class {node.name}")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(f"    def {node.name}.{sub.name}")
    return out


def build(root: Path) -> str:
    lines: list[str] = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        es = _entries(p)
        if not es:
            continue
        lines.append(rel.as_posix())
        lines.extend(es)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Peta simbol repo ringkas.")
    parser.add_argument("--max", type=int, default=7000, help="batas karakter keluaran")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    text = build(root)
    if len(text) > args.max:
        text = text[: args.max] + "\n... (dipotong)"
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
