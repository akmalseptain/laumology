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

RUN_LS=0
if command -v litestream >/dev/null 2>&1 \
   && [ -n "${LITESTREAM_BUCKET:-}" ] \
   && [ -n "${LITESTREAM_ACCESS_KEY_ID:-}" ] \
   && [ -n "${LITESTREAM_SECRET_ACCESS_KEY:-}" ]; then
    RUN_LS=1
    gen_config
    # Pulihkan DB dari replica bila ada; kalau belum ada, biarkan DB baru.
    if ! litestream restore -config /tmp/litestream.yml -if-replica-exists "$DB_PATH"; then
        echo "[render-start] restore dilewati (belum ada replica / gagal) — lanjut dengan DB baru."
    fi
else
    echo "[render-start] Litestream NONAKTIF (binary/env belum lengkap) — gunicorn biasa."
fi

if [ "$RUN_LS" = "1" ]; then
    echo "[render-start] Litestream AKTIF: DB=$DB_PATH replica=$LITESTREAM_BUCKET"
    exec litestream replicate -config /tmp/litestream.yml \
        -exec "gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120 webapp:app"
fi

exec gunicorn --bind 0.0.0.0:"$PORT" --workers 1 --threads 8 --timeout 120 webapp:app
