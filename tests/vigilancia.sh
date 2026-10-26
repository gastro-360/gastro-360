#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Simula la caída del contenedor app y comprueba que el vigilante avisa (a un Telegram simulado) de la caída y de la recuperación.
# Proyecto aparte, sin Caddy ni puertos publicados. Al acabar lo borra todo (down -v), salvo con CONSERVAR=1.
#   tests/vigilancia.sh
set -euo pipefail
cd "$(dirname "$0")/.."
RESTAURANTE="${RESTAURANTE:-demo}"   # el restaurante contra el que se prueba
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"

ENVF="$(mktemp)"
cat > "$ENVF" <<ENV
RESTAURANTE=$RESTAURANTE
CLAVE_BACKOFFICE=prueba-$RANDOM$RANDOM
TELEGRAM_BOT_TOKEN=TOKEN-DE-PRUEBA
TELEGRAM_CHAT_ID=12345
TELEGRAM_API_URL=http://telegram-mock:9000
VIGILANTE_INTERVALO=2
VIGILANTE_FALLOS=2
ENV
dc() { docker compose -p cartavigil -f docker-compose.yml -f tests/vigilancia.compose.yml --env-file "$ENVF" "$@"; }
limpiar() { [ "${CONSERVAR:-0}" = 1 ] || dc down -v --remove-orphans >/dev/null 2>&1 || true; rm -f "$ENVF"; }
trap limpiar EXIT
mensajes() { dc exec -T -e PYTHONIOENCODING=utf-8 telegram-mock python -c "import json,urllib.request;[print(m['text']) for m in json.load(urllib.request.urlopen('http://127.0.0.1:9000/mensajes'))]"; }
# espera hasta 60 s a que algún mensaje contenga $1
esperar() { for _ in $(seq 60); do mensajes | grep -q "$1" && return 0; sleep 1; done; echo "NO llegó un aviso con «$1». Mensajes: $(mensajes)"; dc logs --no-log-prefix --tail 15 vigilante; return 1; }

dc down -v --remove-orphans >/dev/null 2>&1 || true
echo "== docker compose build + up -d (app + vigilante + telegram-mock; una sola imagen)"; dc build app; dc up -d --wait --wait-timeout 180 app vigilante telegram-mock
echo "== con la app sana, pasados unos ciclos, no debe haber avisos de caída"; sleep 8
mensajes | grep -q "CAÍDA" && { echo "FALLA: aviso de caída con la app sana"; exit 1; }
echo "mensajes: $(mensajes)"

echo "== simulo la caída: docker compose stop app"; dc stop app
esperar "CAÍDA"; echo "aviso de caída recibido"
echo "== recupero: docker compose start app"; dc start app
esperar "recuperada"; echo "aviso de recuperación recibido"
echo "== mensajes finales:"; mensajes
[ "$(mensajes | grep -o 'CAÍDA' | wc -l)" = 1 ] || { echo "FALLA: el aviso de caída debía ser uno solo"; exit 1; }
echo "TODO OK"
