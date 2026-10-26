#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Instalador de un comando. Solo necesita Docker y Docker Compose.
#   ./instalar.sh               prueba local: restaurante demo, sin preguntas, correo y Wallet simulados
#   ./instalar.sh --produccion  servidor real: pregunta nombre, dominio y clave; HTTPS con Caddy; no simula nada
# No sube nada a ningún sitio: solo escribe el .env (fuera de git) y levanta los contenedores de este repositorio.
# Variables opcionales: HTTP_PORT, HTTPS_PORT, PROYECTO (nombre del proyecto de Docker Compose, por defecto gastro360).
set -euo pipefail
cd "$(dirname "$0")"

MODO=local
case "${1:-}" in
  "") ;;
  --produccion) MODO=produccion ;;
  -h|--ayuda|--help) sed -n 3,7p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "Opción desconocida: $1 (usa --produccion o ninguna)" >&2; exit 2 ;;
esac

fallo() { echo "ERROR: $*" >&2; exit 1; }

# ---------- Docker ----------
command -v docker >/dev/null 2>&1 || fallo "No encuentro Docker. Instálalo desde https://docs.docker.com/engine/install/ y vuelve a ejecutar ./instalar.sh"
if ! docker info >/dev/null 2>&1; then
  sock="/run/user/$(id -u)/docker.sock"   # Docker rootless
  if [ -S "$sock" ]; then export XDG_RUNTIME_DIR="/run/user/$(id -u)" DOCKER_HOST="unix://$sock"; fi
  docker info >/dev/null 2>&1 || fallo "Docker está instalado pero no responde. Arráncalo (p. ej. «sudo systemctl start docker») o añade tu usuario al grupo docker."
fi
docker compose version >/dev/null 2>&1 || fallo "Falta «docker compose» (el plugin Compose v2). Instálalo: https://docs.docker.com/compose/install/"

# ---------- utilidades ----------
aleatoria() { od -An -N12 -tx1 /dev/urandom | tr -d ' \n'; }   # 24 caracteres hexadecimales
ocupado() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
libre_desde() { local p=$1; while ocupado "$p"; do p=$((p + 1)); done; echo "$p"; }
leer_env() { sed -n "s/^$1=//p" .env | tail -n 1 | sed "s/^'\(.*\)'$/\1/"; }
numero() { [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
preguntar() {   # preguntar "texto" [defecto]  ->  respuesta en $RESPUESTA
  local r; read -r -p "$1${2:+ [$2]}: " r || r=""
  RESPUESTA="${r:-${2:-}}"
}

# ---------- .env ----------
CLAVE_NUEVA=""
if [ -f .env ]; then
  if [ "$MODO" = produccion ]; then
    preguntar "Ya existe un .env. ¿Lo sobrescribo? (se guarda copia en .env.anterior) [s/N]" "n"
    case "$RESPUESTA" in
      s|S|si|sí|SI|Sí) cp -p .env .env.anterior; rm -f .env ;;
      *) echo "Dejo el .env como está y solo arranco."; ;;
    esac
  else
    echo "Ya existe un .env: lo dejo como está y solo arranco."
  fi
fi

if [ ! -f .env ]; then
  PROYECTO="${PROYECTO:-gastro360}"
  umask 077
  if [ "$MODO" = local ]; then
    HTTP_PORT="${HTTP_PORT:-$(libre_desde 8080)}"
    HTTPS_PORT="${HTTPS_PORT:-$(libre_desde 8443)}"
    numero "$HTTP_PORT" && numero "$HTTPS_PORT" || fallo "Puerto no válido (HTTP_PORT=$HTTP_PORT, HTTPS_PORT=$HTTPS_PORT)"
    ocupado "$HTTP_PORT" && fallo "El puerto $HTTP_PORT ya está en uso. Elige otro: HTTP_PORT=9080 ./instalar.sh"
    CLAVE_NUEVA="$(aleatoria)"
    cat > .env <<ENV
# Generado por instalar.sh (prueba local). Contiene la clave del backoffice: no lo subas a ningún sitio.
COMPOSE_PROJECT_NAME=$PROYECTO
RESTAURANTE=demo
DOMINIO=http://localhost
HTTP_PORT=$HTTP_PORT
HTTPS_PORT=$HTTPS_PORT
URL_PUBLICA=http://localhost:$HTTP_PORT
CLAVE_BACKOFFICE='$CLAVE_NUEVA'
# Prueba local: el correo y Wallet son simulados (nada sale a Internet). Bórralos para ver cómo se comporta sin credenciales.
CORREO_MODO=prueba
WALLET_MODO=prueba
ENV
  else
    preguntar "Nombre del restaurante" "Mi restaurante"; NOMBRE="$RESPUESTA"
    [[ "$NOMBRE" != *$'\n'* ]] || fallo "El nombre no puede tener saltos de línea."
    SLUG="$(printf '%s' "$NOMBRE" | { iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null || cat; } | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9]\{1,\}/-/g; s/^-//; s/-$//')"
    SLUG="${SLUG:-restaurante}"
    while :; do
      preguntar "Dominio (ya apuntando a este servidor, p. ej. carta.turestaurante.es)"; DOMINIO="$RESPUESTA"
      [[ "$DOMINIO" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ && "$DOMINIO" == *.* ]] && break
      echo "  Escribe solo el dominio, sin https:// ni barras (ejemplo: carta.turestaurante.es)."
    done
    while :; do
      read -r -s -p "Clave del backoffice (vacía = la genero yo, mínimo 8 caracteres): " CLAVE || CLAVE=""; echo
      if [ -z "$CLAVE" ]; then CLAVE="$(aleatoria)"; CLAVE_NUEVA="$CLAVE"; break; fi
      if [ "${#CLAVE}" -ge 8 ] && [[ "$CLAVE" != *"'"* && "$CLAVE" != *$'\n'* ]]; then break; fi
      echo "  Mínimo 8 caracteres y sin comillas simples."
    done
    HTTP_PORT="${HTTP_PORT:-80}"; HTTPS_PORT="${HTTPS_PORT:-443}"
    numero "$HTTP_PORT" && numero "$HTTPS_PORT" || fallo "Puerto no válido (HTTP_PORT=$HTTP_PORT, HTTPS_PORT=$HTTPS_PORT)"
    URL="https://$DOMINIO"; [ "$HTTPS_PORT" = 443 ] || URL="$URL:$HTTPS_PORT"
    cat > .env <<ENV
# Generado por instalar.sh --produccion. Contiene la clave del backoffice: no lo subas a ningún sitio.
COMPOSE_PROJECT_NAME=$PROYECTO
RESTAURANTE=$SLUG
DOMINIO=$DOMINIO
HTTP_PORT=$HTTP_PORT
HTTPS_PORT=$HTTPS_PORT
URL_PUBLICA=$URL
CLAVE_BACKOFFICE='$CLAVE'
# Aquí no se simula nada. Lo que falta se explica en el propio backoffice y en docs/INSTALAR-AVANZADO.md:
# correo de promociones (Brevo): rellena las dos siguientes
BREVO_API_KEY=
BREVO_REMITENTE=
# aviso de caída por Telegram: rellena las dos siguientes
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ENV
  fi
  chmod 600 .env
fi

# ---------- imagen: se construye aquí, desde este repo ----------
dc() { docker compose "$@"; }
echo "== Construyo la imagen (unos minutos la primera vez; luego, segundos)"
dc build app

# ---------- restaurante nuevo (solo producción) ----------
if [ "$MODO" = produccion ] && [ -n "${SLUG:-}" ]; then
  dc run --rm --no-deps --entrypoint python app /app/carta/nuevo_restaurante.py "$SLUG" --nombre "$NOMBRE" \
    || echo "(el restaurante '$SLUG' ya existía en los datos: lo dejo como está)"
fi

echo "== Arranco"
dc up -d --wait --wait-timeout 240 || { dc logs --tail 40 >&2 || true; fallo "Los contenedores no han quedado sanos. Mira los registros de arriba."; }

# ---------- resumen ----------
BASE="$(leer_env URL_PUBLICA)"
echo
echo "Listo. Gastro 360 está funcionando:"
echo "  Carta:      $BASE/"
echo "  Cocina:     $BASE/cocina"
echo "  Backoffice: $BASE/admin"
if [ -n "$CLAVE_NUEVA" ]; then
  echo "  Clave del backoffice (se muestra solo ahora; queda en el archivo .env): $CLAVE_NUEVA"
else
  echo "  Clave del backoffice: la de CLAVE_BACKOFFICE en el archivo .env"
fi
if [ "$MODO" = local ]; then
  echo
  echo "Es una prueba local con el restaurante demo: el correo y Wallet están simulados. Para un servidor real: ./instalar.sh --produccion"
else
  echo
  echo "Sin credenciales de terceros, Sellos con Wallet y Promociones por correo salen desactivados y el backoffice explica cómo activarlos."
  echo "Si el dominio aún no apunta a este servidor, el HTTPS no se emitirá hasta que lo haga."
fi
echo "Parar:  docker compose down   ·   Borrar también los datos:  docker compose down -v"
