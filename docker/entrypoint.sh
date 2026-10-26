#!/bin/sh
# SPDX-License-Identifier: EUPL-1.2
# Prepara el volumen /datos la primera vez y arranca el servidor. Todo a stdout (docker logs).
set -e
R="${RESTAURANTE:-demo}"
mkdir -p "$CARTA_RESTAURANTES"
if [ ! -d "$CARTA_RESTAURANTES/$R" ]; then
  if [ -d "/app/restaurantes/$R" ]; then
    echo "Primera vez: copio la carta de $R al volumen de datos"
    cp -r "/app/restaurantes/$R" "$CARTA_RESTAURANTES/$R"
  else
    echo "No existe el restaurante '$R' (ni en el volumen ni en la imagen)" >&2
    exit 1
  fi
fi
cd /app/carta
python preparar_netlify.py
exec python servidor.py
