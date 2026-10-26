<!-- SPDX-License-Identifier: EUPL-1.2 -->
# Diseño (marca blanca)

**Dirección**: producto sobrio y neutro para cocina y sala; la marca la pone cada restaurante en `marca.json`, el producto no tiene identidad propia. Tema oscuro o claro según el fondo elegido.

**Principios**: carta primero en móvil (360 px) y usable a 1280; cocina legible a distancia (letra grande, botones de 56 px); backoffice a 1280 con pestañas. Sin gradientes, sin sombras en reposo, un solo tipo de letra (Inter), cifras tabulares, escala 12/14/16/24/32 px, objetivos táctiles ≥ 44 px, foco visible, alérgenos siempre con texto, `lang` por idioma.

**Jerarquía**: título y precio primero; el acento solo para lo que pide acción o atención (alérgenos, nuevos pedidos, cambios del cliente); lo secundario en `--tinta-2`.

**Tokens** (`carta/tema.py` → `/tema.css`, desde `marca.json`; lo ausente cae a un tema neutro): `--fondo --superficie --superficie-2 --linea --linea-fuerte --tinta --tinta-2 --primario --acento --peligro --ok` (con sus `--sobre-*`, `--*-texto`, `--*-suave`), `--r --r-ctl --r-chip` (radios), `--u` (unidad de espaciado, `forma.densidad`), `--f-titulos --f-texto --f-mono`. Las escalas fijas (`--t-*`, `--s-*`, `--objetivo`) están en `carta/estatico/base.css`. El contraste (tinta ≥ 12:1, texto de color ≥ 4,5:1, bordes de control ≥ 3:1) se corrige por código, no a mano.

**Fuentes**: Inter y Noto Sans SC variables (OFL) en `carta/estatico/fuentes/`; el chino va por trozos `unicode-range`. Nada de terceros en el navegador.

