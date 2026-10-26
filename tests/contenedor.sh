#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Batería contra el contenedor: levanta el compose en un proyecto aparte (volúmenes propios), espera al healthcheck,
# pasa la batería de tests/ DENTRO del contenedor, la batería HTTP desde fuera (por Caddy, HTTPS) y comprueba que el volumen
# conserva los datos tras `docker compose restart`. Al acabar lo borra todo (down -v), salvo con CONSERVAR=1.
#   tests/contenedor.sh          (puertos 18080/18443 por defecto: CARTA_HTTP_PORT / CARTA_HTTPS_PORT)
set -euo pipefail
cd "$(dirname "$0")/.."
RESTAURANTE="${RESTAURANTE:-demo}"   # el restaurante contra el que se prueba
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"

HTTP="${CARTA_HTTP_PORT:-18080}"; HTTPS="${CARTA_HTTPS_PORT:-18443}"; CLAVE="prueba-$RANDOM$RANDOM"
ENVF="$(mktemp)"
cat > "$ENVF" <<ENV
RESTAURANTE=$RESTAURANTE
DOMINIO=localhost
HTTP_PORT=$HTTP
HTTPS_PORT=$HTTPS
CLAVE_BACKOFFICE=$CLAVE
COPIA_HORAS=6
WALLET_MODO=prueba
CORREO_MODO=prueba
MAX_PEDIDOS_IP=200
MAX_RESERVAS_IP=200
URL_PUBLICA=https://localhost:$HTTPS
ENV
dc() { docker compose -p cartatest --env-file "$ENVF" "$@"; }
limpiar() { [ "${CONSERVAR:-0}" = 1 ] || dc down -v --remove-orphans >/dev/null 2>&1 || true; rm -f "$ENVF"; }
trap limpiar EXIT

export CARTA_URL="https://localhost:$HTTPS" CARTA_CLAVE="$CLAVE" CARTA_HTTP_PORT="$HTTP"
dc down -v --remove-orphans >/dev/null 2>&1 || true
echo "== docker compose up -d --build"; dc build app; dc up -d --wait --wait-timeout 180
echo "== contenedor app:"; dc ps --format '{{.Service}} {{.Status}}'
[ "$(docker inspect --format '{{.State.Health.Status}}' "$(dc ps -q app)")" = healthy ] || { echo "app NO está healthy"; exit 1; }

echo "== batería de tests/ dentro del contenedor"; dc exec -T app python -m unittest discover -s /app/tests -p 'test_plantilla.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_clientes.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_sellos.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_promociones.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_kpis.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_vigilante.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_seguridad.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_exportar.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_red.py' 2>&1 | tail -5
dc exec -T app python -m unittest discover -s /app/tests -p 'test_alergenos.py' 2>&1 | tail -5
echo "== batería HTTP contra el contenedor (Caddy, HTTPS)"; python3 tests/test_contenedor.py

echo "== persistencia: cambio un dato, reinicio y compruebo que sigue"
COOKIES="$(mktemp)"
curl -sk -c "$COOKIES" -H 'Content-Type: application/json' -d "{\"clave\":\"$CLAVE\"}" "$CARTA_URL/api/login" >/dev/null
curl -sk -b "$COOKIES" -H 'Content-Type: application/json' -d '{"aceptar_pedidos":false}' "$CARTA_URL/api/aceptar" >/dev/null
curl -sk -b "$COOKIES" -H 'Content-Type: application/json' -d '{"mesa":1,"lineas":[{"pid":"'"$(curl -sk "$CARTA_URL/datos.js" | python3 -c 'import sys,json;t=sys.stdin.read();d=json.loads(t.split("window.DATOS = ",1)[1].split(";\nwindow.",1)[0]);print(d["platos"][0]["id"])')"'"}]}' "$CARTA_URL/api/pedido" -o /dev/null
curl -sk -b "$COOKIES" -H 'Content-Type: application/json' -d '{"aceptar_pedidos":true}' "$CARTA_URL/api/aceptar" >/dev/null
ANTES="$(curl -sk -b "$COOKIES" "$CARTA_URL/api/pedidos" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["pedidos"]))')"
curl -sk -b "$COOKIES" -H 'Content-Type: application/json' -d '{"aceptar_pedidos":false}' "$CARTA_URL/api/aceptar" >/dev/null
dc restart app caddy; dc up -d --wait --wait-timeout 120 >/dev/null
curl -sk -c "$COOKIES" -H 'Content-Type: application/json' -d "{\"clave\":\"$CLAVE\"}" "$CARTA_URL/api/login" >/dev/null
DESPUES="$(curl -sk -b "$COOKIES" "$CARTA_URL/api/pedidos" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["pedidos"]))')"
CERRADO="$(curl -sk "$CARTA_URL/api/estado")"
echo "pedidos antes=$ANTES después=$DESPUES · estado tras reinicio: $CERRADO"
rm -f "$COOKIES"
[ "$ANTES" = "$DESPUES" ] && [ "$ANTES" -ge 1 ] && echo "$CERRADO" | grep -q '"aceptar_pedidos": false' || { echo "FALLA la persistencia"; exit 1; }
echo "== freno de intentos: un CF-Connecting-IP distinto en cada petición no lo evade (a través de Caddy)"; CARTA_FRENO=1 python3 tests/test_contenedor.py Freno || { echo "FALLA el freno"; exit 1; }
echo "== copia de pedidos bajo demanda"; dc exec -T app python -c "import sys; sys.path.insert(0,'/app/carta'); import servidor; print(servidor.copiar_pedidos())"
echo "== logs a stdout (últimas líneas de app)"; dc logs --no-log-prefix --tail 6 app
echo "TODO OK"
