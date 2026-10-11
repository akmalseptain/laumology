"""Gerbang kualitas lokal LAUMOLOGY (tanpa dependensi tambahan).

Menjalankan dua pemeriksaan:
- ``--syntax``: memindai seluruh ``*.py`` di root repo dan meng-``compile()``-nya
  (tidak menulis berkas ``.pyc``).
- ``--tests``: menjalankan suite regresi ``tests.test_engine``.

Bila dipanggil tanpa argumen, kedua pemeriksaan dijalankan. Kode keluar 0 bila
semua lolos, 1 bila ada kegagalan.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Direktori yang dilewati saat pemindaian sintaks (bukan kode sumber aplikasi).
_SKIP_DIRS = {
    ".git",
    ".cache",
    "output",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "Sciencebasedlifter",
    "state",
}


def iter_py_files() -> list[pathlib.Path]:
    """Kumpulkan berkas ``*.py`` di root repo, lewati direktori terlarang."""
    files: list[pathlib.Path] = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        files.append(path)
    return files


def check_syntax() -> list[str]:
    """Baca + ``compile()`` tiap berkas. Kembalikan daftar pesan kegagalan."""
    failures: list[str] = []
    for path in iter_py_files():
        rel = path.relative_to(ROOT)
        try:
            # utf-8-sig: varian UTF-8 yang menoleransi BOM (dianggap sah oleh
            # tokenizer Python); compile() atas str menolak U+FEFF mentah.
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"{rel}: gagal dibaca ({exc})")
            continue
        try:
            # compile() hanya memvalidasi; tidak menulis .pyc.
            compile(source, str(rel), "exec")
        except SyntaxError as exc:
            failures.append(f"{rel}:{exc.lineno}: {exc.msg}")
    return failures


def run_tests(verbose: bool) -> bool:
    """Jalankan suite ``tests.test_engine``. True bila sukses."""
    # Skrip dijalankan sebagai ``py tools/quality_gate.py`` -> sisipkan root.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_engine")
    except Exception as exc:  # noqa: BLE001 - laporkan gagal muat apa adanya
        print(f"[quality-gate] GAGAL memuat tests.test_engine: {exc}")
        return False
    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    return result.wasSuccessful()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gerbang kualitas lokal LAUMOLOGY.",
    )
    parser.add_argument(
        "--syntax",
        action="store_true",
        help="hanya periksa sintaks seluruh modul Python",
    )
    parser.add_argument(
        "--tests",
        action="store_true",
        help="hanya jalankan suite regresi tests.test_engine",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="verbositas output test",
    )
    args = parser.parse_args(argv)

    # Tanpa flag apa pun -> jalankan kedua pemeriksaan.
    no_flags = not args.syntax and not args.tests
    do_syntax = args.syntax or no_flags
    do_tests = args.tests or no_flags

    passed = True

    if do_syntax:
        files = iter_py_files()
        failures = check_syntax()
        print(
            f"[quality-gate] sintaks: {len(files)} berkas diperiksa, "
            f"{len(failures)} gagal"
        )
        for message in failures:
            print(f"[quality-gate]   - {message}")
        if failures:
            passed = False

    if do_tests:
        print("[quality-gate] menjalankan tests.test_engine ...")
        if not run_tests(args.verbose):
            passed = False

    if passed:
        print("[quality-gate] HASIL: LULUS")
        return 0
    print("[quality-gate] HASIL: GAGAL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
