#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Línea roja: ningún nombre ni dato de un restaurante o empresa concretos en el repo (contenido, nombres de fichero, mensajes de commit).
# Los nombres a vigilar NO van en el repo: se leen de tests/lineas-rojas.local (uno por línea, expresión regular extendida;
# ignorado por git) o de la variable LINEAS_ROJAS (separados por «|»). Sale ≠ 0 si hay una sola coincidencia.
#   bash tests/lineas-rojas.sh
cd "$(dirname "$0")/.."
LOCAL="tests/lineas-rojas.local"
if [ -n "$LINEAS_ROJAS" ]; then
  PATRON="$LINEAS_ROJAS"
elif [ -f "$LOCAL" ]; then
  PATRON="$(grep -vE '^\s*(#|$)' "$LOCAL" | paste -sd'|')"
fi
[ -n "$PATRON" ] || { echo "sin nombres que vigilar: crea $LOCAL o define LINEAS_ROJAS"; exit 2; }
n=0
echo "== contenido de los ficheros del repo (git grep)"
c="$(git grep -niE "$PATRON" -- . 2>/dev/null)"; [ -n "$c" ] && { echo "$c"; n=$((n + $(echo "$c" | wc -l))); }
echo "== nombres de fichero (git ls-files)"
f="$(git ls-files | grep -iE "$PATRON")"; [ -n "$f" ] && { echo "$f"; n=$((n + $(echo "$f" | wc -l))); }
echo "== mensajes y autoría de los commits de la rama actual"
h="$(git log --format='%H %an %ae%n%B' | grep -iE "$PATRON")"; [ -n "$h" ] && { echo "$h"; n=$((n + $(echo "$h" | wc -l))); }
echo "coincidencias: $n"
[ "$n" -eq 0 ] && echo "LÍNEAS ROJAS (nombres): OK" || { echo "LÍNEAS ROJAS (nombres): FALLA"; exit 1; }
