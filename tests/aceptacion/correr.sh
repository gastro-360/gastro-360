#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Corre los casos automatizables de docs/GUION-ACEPTACION.md contra CUALQUIER dirección (local o entorno de pruebas remoto).
#   tests/aceptacion/correr.sh BASE_URL CLAVE [--solo CA-01,CA-17]
# Opcional por entorno: QA_BASIC_USUARIO + QA_BASIC_CLAVE (usuario y contraseña HTTP delante del sitio; nunca se imprimen ni se guardan),
# QA_RED (argumento --network de docker: por defecto la red normal; tests/aceptacion.sh lo usa para llegar al compose local),
# QA_VERSION_ESPERADA (la versión que debe decir /salud), QA_SALIDA (carpeta de capturas y resultado.json; por defecto tests/aceptacion/salida/).
# Usa la imagen de tests/e2e (Playwright + Chromium). Sale con código ≠ 0 si algún caso falla.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ $# -ge 2 ] || { echo "uso: tests/aceptacion/correr.sh BASE_URL CLAVE [--solo CA-01,CA-02]" >&2; exit 2; }
BASE_URL="$1"; CLAVE="$2"; shift 2
SOLO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --solo) SOLO="${2:-}"; shift 2 ;;
    *) echo "argumento desconocido: $1" >&2; exit 2 ;;
  esac
done
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
SALIDA="${QA_SALIDA:-$PWD/tests/aceptacion/salida}"; mkdir -p "$SALIDA"
rm -f "$SALIDA"/*.png "$SALIDA"/resultado.json

docker build -q -t carta-e2e:local tests/e2e >/dev/null
export QA_BASE_URL="$BASE_URL" QA_CLAVE="$CLAVE" QA_SOLO="$SOLO"
# -e NOMBRE sin valor: el secreto no aparece en la línea de comandos.
docker run --rm --ipc=host ${QA_RED:+--network "$QA_RED"} \
  -v "$PWD/tests/aceptacion:/aceptacion:ro" -v "$PWD:/repo:ro" -v "$SALIDA:/salida" \
  -e QA_BASE_URL -e QA_CLAVE -e QA_SOLO -e QA_BASIC_USUARIO -e QA_BASIC_CLAVE -e QA_VERSION_ESPERADA \
  -e QA_SALIDA=/salida -e QA_REPO=/repo -e PYTHONUNBUFFERED=1 \
  carta-e2e:local python /aceptacion/correr.py
