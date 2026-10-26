#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# E2E: levanta el compose en un proyecto aparte, deja la reseña de Google activa con un enlace de PRUEBA, y lanza
# Playwright (Chromium headless en una imagen de pruebas propia, tests/e2e/Dockerfile) pegado a la red de Caddy: varios móviles a 360 px a la
# vez, cocina, backoffice y tarjeta, también a 1280 px. Al acabar lo borra todo (down -v), salvo con CONSERVAR=1.
#   tests/e2e.sh      (puertos 19080/19443 por defecto: E2E_HTTP_PORT / E2E_HTTPS_PORT)  ·  capturas en tests/e2e/salida/
set -euo pipefail
cd "$(dirname "$0")/.."
RESTAURANTE="${RESTAURANTE:-demo}"   # el restaurante contra el que se prueba
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"

HTTP="${E2E_HTTP_PORT:-19080}"; HTTPS="${E2E_HTTPS_PORT:-19443}"; CLAVE="e2e-$RANDOM$RANDOM"
ENVF="$(mktemp)"; SALIDA="$PWD/tests/e2e/salida"; mkdir -p "$SALIDA"
cat > "$ENVF" <<ENV
RESTAURANTE=$RESTAURANTE
DOMINIO=localhost
HTTP_PORT=$HTTP
HTTPS_PORT=$HTTPS
CLAVE_BACKOFFICE=$CLAVE
COPIA_HORAS=6
WALLET_MODO=prueba
CORREO_MODO=prueba
MAX_PEDIDOS_IP=500
MAX_RESERVAS_IP=500
URL_PUBLICA=https://localhost:$HTTPS
ENV
dc() { docker compose -p cartae2e --env-file "$ENVF" "$@"; }
limpiar() { [ "${CONSERVAR:-0}" = 1 ] || dc down -v --remove-orphans >/dev/null 2>&1 || true; rm -f "$ENVF"; }
trap limpiar EXIT

dc down -v --remove-orphans >/dev/null 2>&1 || true
echo "== docker compose up -d --build"; dc build app; dc up -d --wait --wait-timeout 180

# Un restaurante recién instalado no tiene google_place_id: para ver el botón de reseña se pone un enlace de PRUEBA solo en el volumen de este proyecto.
echo "== enlace de reseña de prueba en el volumen (no toca git) y reinicio de app"
dc exec -T app python -c "
import json
r='/datos/restaurantes/$RESTAURANTE/marca.json'; m=json.load(open(r, encoding='utf-8'))
m['resena_url']='https://search.google.com/local/writereview?placeid=ChIJ_PRUEBA_E2E'
json.dump(m, open(r,'w',encoding='utf-8'), ensure_ascii=False, indent=1)"
dc restart app; dc up -d --wait --wait-timeout 120 >/dev/null
echo "== contenedores:"; dc ps --format '{{.Service}} {{.Status}}'

echo "== Playwright (imagen carta-e2e:local) en la red de Caddy"
docker build -q -t carta-e2e:local tests/e2e >/dev/null
docker run --rm --ipc=host --network "container:$(dc ps -q caddy)" \
  -v "$PWD/tests/e2e:/e2e:ro" -v "$SALIDA:/salida" \
  -e CARTA_URL="https://localhost:$HTTPS" -e CARTA_CLAVE="$CLAVE" -e SALIDA=/salida -e PYTHONUNBUFFERED=1 -e CONFIRMACION_DOBLE="${CONFIRMACION_DOBLE:-}" \
  carta-e2e:local python /e2e/test_e2e.py
echo "E2E OK"
