#!/bin/sh
# Build LAUMOLOGY di Render: unduh Litestream versi PIN (bukan "latest") ke ./bin.
# Alasan pin: URL asset "releases/latest/download/..." bisa berubah tanpa gelar
# (v0.5.x mengganti nama asset) dan menyebabkan build gagal total.
# Kegagalan unduh TIDAK memutuskan build (exit 0) - status terlihat via /health.
set -u
BIN_DIR="bin"
LITESTREAM_VERSION="0.5.17"
LITESTREAM_URL="https://github.com/benbjohnson/litestream/releases/download/v0.5.17/litestream-0.5.17-linux-x86_64.tar.gz"
TMP_TGZ="/tmp/litestream-build.tgz"

mkdir -p "$BIN_DIR"

if curl -fsSL "$LITESTREAM_URL" -o "$TMP_TGZ" || wget -q "$LITESTREAM_URL" -O "$TMP_TGZ"; then
  if tar -xzf "$TMP_TGZ" -C "$BIN_DIR" litestream && chmod +x "$BIN_DIR/litestream"; then
    if "$BIN_DIR/litestream" version >/dev/null 2>&1; then
      echo "[render-build] Litestream $LITESTREAM_VERSION terpasang di $BIN_DIR/"
    else
      echo "[render-build] PERINGATAN: binary litestream tidak bisa dijalankan"
    fi
  else
    echo "[render-build] PERINGATAN: ekstraksi litestream GAGAL - DB non-persisten"
  fi
else
  echo "[render-build] PERINGATAN: unduhan litestream GAGAL - DB non-persisten. URL: $LITESTREAM_URL"
fi

exit 0
