#!/bin/sh
# Arranque del contenedor de la API: migraciones y luego uvicorn.
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    alembic upgrade head
fi

# Un solo proceso a propósito: los workers de generación, calendario y retención son
# hilos de este proceso, y el bus del canal SSE vive en su memoria.
exec uvicorn dossier.api.app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips "*" \
    --root-path "${API_ROOT_PATH:-/api}"
