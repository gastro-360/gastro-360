#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Privacidad: levanta la app con un .env de restaurante recién instalado (SIN credenciales y SIN modos de prueba) y comprueba con
# Playwright que el navegador solo habla con el propio servidor (carta, cocina, backoffice, tarjeta, baja) y que las cabeceras de
# seguridad están. Con --negativa se mete un <link> a un host externo en la portada y el test DEBE fallar (prueba de la prueba).
#   tests/privacidad.sh [--negativa]      Al acabar borra todo (down -v), salvo con CONSERVAR=1.
set -euo pipefail
cd "$(dirname "$0")/.."
RESTAURANTE="${RESTAURANTE:-demo}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
CLAVE="priv-$RANDOM$RANDOM"; ENVF="$(mktemp)"
printf 'RESTAURANTE=%s\nCLAVE_BACKOFFICE=%s\nHTTP_PORT=%s\nHTTPS_PORT=%s\nMAX_PEDIDOS_IP=500\nMAX_RESERVAS_IP=500\n' "$RESTAURANTE" "$CLAVE" "${PRIV_HTTP_PORT:-19180}" "${PRIV_HTTPS_PORT:-19543}" > "$ENVF"
dc() { docker compose -p cartapriv --env-file "$ENVF" "$@"; }
limpiar() { [ "${CONSERVAR:-0}" = 1 ] || dc down -v --remove-orphans >/dev/null 2>&1 || true; rm -f "$ENVF"; }
trap limpiar EXIT
dc down -v --remove-orphans >/dev/null 2>&1 || true
echo "== docker compose up (app, sin credenciales ni modos de prueba)"; dc build app >/dev/null; dc up -d --wait --wait-timeout 180 app

if [ "${1:-}" = "--negativa" ]; then
  echo "== prueba negativa: <link> a un host externo en la portada (solo en este contenedor)"
  dc exec -T app python -c "
p='/app/web/index.html'; s=open(p,encoding='utf-8').read()
open(p,'w',encoding='utf-8').write(s.replace('<title>','<link rel=\"stylesheet\" href=\"https://recurso-externo.example/x.css\"><title>',1))"
fi

docker build -q -t carta-e2e:local tests/e2e >/dev/null
# http://localhost dentro de la red del contenedor de la app: contexto seguro, así el service worker también se registra
set +e
docker run --rm --ipc=host --network "container:$(dc ps -q app)" -v "$PWD/tests/privacidad:/privacidad:ro" \
  -e CARTA_URL="http://localhost:8080" -e CARTA_CLAVE="$CLAVE" -e PYTHONUNBUFFERED=1 carta-e2e:local python /privacidad/test_privacidad.py
rc=$?; set -e
if [ "${1:-}" = "--negativa" ]; then
  [ $rc -ne 0 ] && { echo "NEGATIVA OK: el test falló como debía"; exit 0; } || { echo "NEGATIVA MAL: el test NO detectó el recurso externo"; exit 1; }
fi
[ $rc -eq 0 ] && echo "PRIVACIDAD OK"
exit $rc
