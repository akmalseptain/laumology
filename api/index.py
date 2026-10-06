"""Vercel serverless entry point (WSGI).

Deploy: hubungkan repo ke Vercel. Semua request selain /static/* diarahkan
ke fungsi ini oleh vercel.json. Konfigurasi rahasia lewat Environment Variables
di dashboard Vercel (API_KEY, OPENAI_API_KEY, IDX_ALERT_WEBHOOK, dll).
"""
from __future__ import annotations

import os
import sys

# pastikan modul root project bisa diimpor dari dalam folder api/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import app  # noqa: E402,F401  (WSGI callable untuk Vercel)
