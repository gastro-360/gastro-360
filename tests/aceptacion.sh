#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Puerta de aceptación: levanta el compose local en un proyecto aparte (puertos altos) con un .env como el de un restaurante recién
# instalado (SIN credenciales ni modos prueba), corre el guion automatizable (tests/aceptacion/correr.sh), repite con
# CORREO_MODO=prueba y WALLET_MODO=prueba, y lo borra todo (down -v). Sale ≠ 0 si algún caso falla en cualquiera de los dos escenarios.
#   tests/aceptacion.sh [--solo CA-01,CA-02]     (puertos 19180/19543: ACEPT_HTTP_PORT / ACEPT_HTTPS_PORT)
set -uo pipefail
cd "$(dirname "$0")/.."
RESTAURANTE="${RESTAURANTE:-demo}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
HTTP="${ACEPT_HTTP_PORT:-19180}"; HTTPS="${ACEPT_HTTPS_PORT:-19543}"; CLAVE="acept-$RANDOM$RANDOM"
ENVF="$(mktemp)"
dc() { docker compose -p aceptacion --env-file "$ENVF" "$@"; }
limpiar() { dc down -v --remove-orphans >/dev/null 2>&1 || true; rm -f "$ENVF"; }
trap limpiar EXIT

escenario() {   # $1 = nombre, $2 = modos prueba (vacío o «prueba»)
  cat > "$ENVF" <<ENV
RESTAURANTE=$RESTAURANTE
DOMINIO=localhost
HTTP_PORT=$HTTP
HTTPS_PORT=$HTTPS
CLAVE_BACKOFFICE=$CLAVE
COPIA_HORAS=6
MAX_PEDIDOS_IP=500
MAX_RESERVAS_IP=500
URL_PUBLICA=https://localhost:$HTTPS
WALLET_MODO=$2
CORREO_MODO=$2
ENV
  echo; echo "################ ESCENARIO: $1"
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  dc build app >/dev/null && dc up -d --wait --wait-timeout 180 >/dev/null || { echo "no arranca el compose"; return 1; }
  QA_RED="container:$(dc ps -q caddy)" QA_SALIDA="$PWD/tests/aceptacion/salida/$3" \
    tests/aceptacion/correr.sh "https://localhost:$HTTPS" "$CLAVE" "${@:4}"
}

SOLO=(); [ "${1:-}" = "--solo" ] && SOLO=(--solo "${2:-}")
fallo=0
escenario "restaurante recién instalado (sin credenciales ni modos prueba)" "" sin-credenciales "${SOLO[@]}" || fallo=1
escenario "con CORREO_MODO=prueba y WALLET_MODO=prueba" "prueba" modos-prueba "${SOLO[@]}" || fallo=1
echo; [ $fallo = 0 ] && echo "ACEPTACIÓN: todo en verde" || echo "ACEPTACIÓN: hay casos que fallan (ver tablas)"
exit $fallo
