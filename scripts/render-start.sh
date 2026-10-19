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
# (tanpa harus buka log Render). Nilai: aktif / aktif:restore-error:<detil> /
# nonaktif:binary / nonaktif:env / nonaktif:binary+env.
STATUS_FILE="$DB_DIR/litestream.status"

if command -v litestream >/dev/null 2>&1; then HAVE_BIN=1; else HAVE_BIN=0; fi
if [ -n "${LITESTREAM_BUCKET:-}" ] && [ -n "${LITESTREAM_ACCESS_KEY_ID:-}" ] \
   && [ -n "${LITESTREAM_SECRET_ACCESS_KEY:-}" ]; then HAVE_ENV=1; else HAVE_ENV=0; fi

if [ "$HAVE_BIN" = "1" ] && [ "$HAVE_ENV" = "1" ]; then
    gen_config
    # Pulihkan DB dari replica bila ada; kalau belum ada, biarkan DB baru.
    if litestream restore -config /tmp/litestream.yml -if-replica-exists "$DB_PATH" \
            2>"$DB_DIR/litestream.restore.err"; then
        printf 'aktif' > "$STATUS_FILE"
    else
        # Detil error disanitasi (satu baris, tanpa kredensial — stderr litestream
        # tidak pernah memuat secret) lalu ditulis ke marker supaya penyebabnya
        # terbaca langsung dari /health tanpa harus membuka log Render.
        ERR="$(grep -oE 'api error .*' "$DB_DIR/litestream.restore.err" | head -n1)"
        [ -n "$ERR" ] || ERR="$(head -n1 "$DB_DIR/litestream.restore.err")"
        ERR="$(printf '%s' "$ERR" | tr -d '\r' | tr -c 'a-zA-Z0-9 :._-' ' ' | tr -s ' ' | cut -c1-100)"
        printf 'aktif:restore-error:%s' "$ERR" > "$STATUS_FILE"
        echo "[render-start] restore gagal — lanjut dengan DB baru; replicate tetap jalan."
        echo "[render-start] detail: $(head -n3 "$DB_DIR/litestream.restore.err")"
    fi
else
    if [ "$HAVE_BIN" = "0" ] && [ "$HAVE_ENV" = "0" ]; then WHY="binary+env"
    elif [ "$HAVE_BIN" = "0" ]; then WHY="binary"
    else WHY="env"; fi
    printf 'nonaktif:%s' "$WHY" > "$STATUS_FILE"
    echo "[render-start] Litestream NONAKTIF ($WHY belum lengkap) — gunicorn biasa."
fi

# Marker 'aktif:restore-error:<detil>' harus tetap dihitung AKTIF (prefix-match)
# supaya replicate (streaming backup DB baru) tetap berjalan.
ST="$(cat "$STATUS_FILE" 2>/dev/null)"
case "$ST" in
    aktif|aktif:restore-error*)
        echo "[render-start] Litestream AKTIF: DB=$DB_PATH replica=$LITESTREAM_BUCKET"
        exec litestream replicate -config /tmp/litestream.yml \
            -exec "gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120 webapp:app"
        ;;
esac

exec gunicorn --bind 0.0.0.0:"$PORT" --workers 1 --threads 8 --timeout 120 webapp:app
