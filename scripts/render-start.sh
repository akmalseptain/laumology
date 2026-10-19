#!/bin/sh
# Bootstrap Render (Opsi A — persistensi DB gratis via Litestream).
# Aman dua arah:
# - Env Litestream TIDAK diset  -> jalan persis seperti sebelumnya (gunicorn biasa).
# - Env diset + binary ada      -> DB di-restore dari replica (bila ada) lalu
#   gunicorn dijalankan DI BAWAH litestream replicate (streaming ke object storage).
# Skrip sengaja tidak pernah gagal total: litestream hilang/env kurang => fallback.
set -u

DB_DIR="${DATA_DIR:-.cache}"
DB_PATH="$DB_DIR/laumology.db"
mkdir -p "$DB_DIR"

# Binary litestream dipasang build step ke ./bin (lihat render.yaml).
export PATH="$PWD/bin:$PATH"

gen_config() {
    # Kredensial TIDAK ditulis ke file: litestream membaca
    # LITESTREAM_ACCESS_KEY_ID / LITESTREAM_SECRET_ACCESS_KEY dari env.
    {
        printf 'dbs:\n'
        printf '  - path: %s\n' "$DB_PATH"
        printf '    replicas:\n'
        printf '      - type: s3\n'
        printf '        bucket: %s\n' "${LITESTREAM_BUCKET:?}"
        printf '        path: %s\n' "${LITESTREAM_PATH:-laumology}"
        printf '        region: %s\n' "${LITESTREAM_REGION:-auto}"
        if [ -n "${LITESTREAM_ENDPOINT:-}" ]; then
            printf '        endpoint: %s\n' "$LITESTREAM_ENDPOINT"
        fi
        printf '        retention: %s\n' "${LITESTREAM_RETENTION:-720h}"
        printf '        syncInterval: %s\n' "${LITESTREAM_SYNC_INTERVAL:-60s}"
    } > /tmp/litestream.yml
}

# Marker status dibaca /health supaya persistensi terdiagnosis dari luar
# (tanpa harus buka log Render). Nilai: aktif / aktif:restore-error /
# nonaktif:binary / nonaktif:env / nonaktif:binary+env.
STATUS_FILE="$DB_DIR/litestream.status"

if command -v litestream >/dev/null 2>&1; then HAVE_BIN=1; else HAVE_BIN=0; fi
if [ -n "${LITESTREAM_BUCKET:-}" ] && [ -n "${LITESTREAM_ACCESS_KEY_ID:-}" ] \
   && [ -n "${LITESTREAM_SECRET_ACCESS_KEY:-}" ]; then HAVE_ENV=1; else HAVE_ENV=0; fi

if [ "$HAVE_BIN" = "1" ] && [ "$HAVE_ENV" = "1" ]; then
    gen_config
    # Pulihkan DB dari replica bila ada; kalau belum ada, biarkan DB baru.
    if litestream restore -config /tmp/litestream.yml -if-replica-exists "$DB_PATH"; then
        printf 'aktif' > "$STATUS_FILE"
    else
        printf 'aktif:restore-error' > "$STATUS_FILE"
        echo "[render-start] restore gagal — lanjut dengan DB baru; replicate tetap jalan."
    fi
else
    if [ "$HAVE_BIN" = "0" ] && [ "$HAVE_ENV" = "0" ]; then WHY="binary+env"
    elif [ "$HAVE_BIN" = "0" ]; then WHY="binary"
    else WHY="env"; fi
    printf 'nonaktif:%s' "$WHY" > "$STATUS_FILE"
    echo "[render-start] Litestream NONAKTIF ($WHY belum lengkap) — gunicorn biasa."
fi

if [ -f "$STATUS_FILE" ] && [ "$(cat "$STATUS_FILE" 2>/dev/null)" = "aktif" ] \
   || [ "$(cat "$STATUS_FILE" 2>/dev/null)" = "aktif:restore-error" ]; then
    echo "[render-start] Litestream AKTIF: DB=$DB_PATH replica=$LITESTREAM_BUCKET"
    exec litestream replicate -config /tmp/litestream.yml \
        -exec "gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120 webapp:app"
fi

exec gunicorn --bind 0.0.0.0:"$PORT" --workers 1 --threads 8 --timeout 120 webapp:app
