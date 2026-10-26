#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Pruebas unitarias: cada tests/test_*.py en su propio proceso. Cada módulo fija CARTA_RESTAURANTES y sus datos al importarse
# (carpeta temporal, base de sellos, freno de pedidos), así que juntos en un solo `unittest discover` se pisan entre sí.
# test_contenedor.py no entra: va contra el contenedor levantado y lo lanza tests/contenedor.sh.
#   tests/unitarias.sh [-v]        PYTHON=python3 por defecto. Sale con 1 si falla algún módulo.
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"; fallos=()
for f in test_*.py; do
  m="${f%.py}"; [ "$m" = test_contenedor ] && continue
  if salida=$("$PY" -m unittest "$@" "$m" 2>&1); then
    echo "OK     $m ($(grep -oE '^Ran [0-9]+' <<<"$salida" | cut -d' ' -f2) pruebas)"
  else
    echo "FALLA  $m"; echo "$salida" | grep -vE 'ResourceWarning' | sed 's/^/       /'; fallos+=("$m")
  fi
done
[ ${#fallos[@]} -eq 0 ] && { echo "== Todas las pruebas unitarias pasan"; exit 0; }
echo "== Fallan: ${fallos[*]}"; exit 1
