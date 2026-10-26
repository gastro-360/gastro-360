# SPDX-License-Identifier: EUPL-1.2
"""Recorta las fotos generadas y crea fotos/*.webp + fotos.js para la carta.

Entrada (carpeta fotos_raw/):
  completo_<plato>.png   foto del plato entero
  <plato>.png            despiece: capas separadas por huecos blancos, de arriba abajo
  extras_<n>.png             3 ingredientes sueltos, en franjas horizontales
Las capas de cada imagen salen de datos.json (de arriba abajo).

Uso:  python recorte.py            (procesa todo lo que haya en fotos_raw/)
"""
import json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage

import restaurante
RAW = os.path.join(restaurante.DIR, "fotos_raw")
OUT = os.path.join(restaurante.DIR, "fotos")
FOTOS_JSON = os.path.join(restaurante.DIR, "fotos.json")
FOTOS_JS = os.path.join(restaurante.DIR, "fotos.js")
ANCHO = 1000

def capas_de_la_carta():
    """Capas de cada despiece, DE ARRIBA ABAJO, sacadas de datos.json: pan de arriba, relleno (de arriba abajo) y pan de abajo."""
    with open(os.path.join(restaurante.DIR, "datos.json"), encoding="utf-8") as f:
        platos = json.load(f).get("platos") or []
    return {p["id"]: [f'{p.get("pan", "barra")}_arriba', *reversed(p.get("i") or []), f'{p.get("pan", "barra")}_abajo'] for p in platos}


def extras_de_la_carpeta():
    """Ingredientes sueltos: cada extra_<id>.png de fotos_raw/ es una pieza que se guarda como capa común, sin plato."""
    if not os.path.isdir(RAW):
        return {}
    return {f[:-4]: [f[6:-4]] for f in sorted(os.listdir(RAW)) if f.startswith("extra_") and f.endswith(".png")}


# Ingredientes con huecos interiores (aros) que hay que vaciar
AROS = {"cebolla", "olivas"}
# Ingredientes blancos o muy claros: el fondo se detecta con un umbral más estricto
BLANCOS = {"cebolla", "alioli", "mayonesa", "cabra", "havarti", "barra_abajo", "huevo_duro", "fuet"}

UMBRAL = 232      # fondo: canal mínimo >= UMBRAL ...
DIF = 30          # ... y diferencia entre canales < DIF (blanco o gris claro, no crema)


def es_fondo(rgb, umbral=UMBRAL, dif=DIF):
    mn = rgb.min(axis=2).astype(int)
    mx = rgb.max(axis=2).astype(int)
    return (mn >= umbral) & ((mx - mn) < dif)


def quitar_fondo(img, aros=False, blanco=False, sombra=False):
    rgb = np.asarray(img.convert("RGB"))
    umbral = 250 if blanco else UMBRAL
    cand = es_fondo(rgb, umbral, 8 if blanco else DIF)
    # Solo el fondo conectado con el borde (relleno desde los bordes)
    lab, n = ndimage.label(cand)
    borde = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    fondo = np.isin(lab, list(borde))
    if aros:  # huecos interiores casi blancos y no diminutos
        hueco = es_fondo(rgb, 250, 8) & ~fondo
        lab2, n2 = ndimage.label(hueco)
        if n2:
            tam = ndimage.sum(hueco, lab2, range(1, n2 + 1))
            grandes = [i + 1 for i, t in enumerate(tam) if t > 150]
            fondo |= np.isin(lab2, grandes)
    if sombra:  # sombra gris bajo el pan: gris claro pegado al fondo, solo en la franja inferior del objeto
        filas = np.where((~fondo).any(axis=1))[0]
        if len(filas):
            y_corte = filas[-1] - int((filas[-1] - filas[0]) * 0.18)
            gris = es_fondo(rgb, 180, 16)
            gris[:y_corte] = False
            lab3, _ = ndimage.label(gris | fondo)
            pegados = set(np.unique(lab3[fondo])) | set(np.unique(lab3[-1]))
            fondo |= np.isin(lab3, list(pegados - {0})) & gris
    # Alfa con borde suave: 2 px de transición alrededor del fondo
    alfa = np.where(fondo, 0.0, 1.0)
    borde_px = ndimage.binary_dilation(fondo, iterations=2) & ~fondo
    lum = rgb.min(axis=2).astype(float)
    a_borde = np.clip((255 - lum) / (255 - umbral + 25), 0.25, 1.0)
    alfa[borde_px] = a_borde[borde_px]
    alfa = ndimage.gaussian_filter(alfa, 0.6)
    alfa[fondo & ~ndimage.binary_dilation(~fondo, iterations=1)] = 0
    # Quitar el halo blanco: restar el blanco del fondo en los bordes semitransparentes
    a = np.clip(alfa, 1e-3, 1)[..., None]
    col = (rgb.astype(float) - (1 - a) * 255) / a
    col = np.clip(col, 0, 255)
    out = np.dstack([col, alfa[..., None] * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def recortar(im):
    bb = im.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    return im.crop(bb) if bb else im


def guardar(im, nombre):
    im = recortar(im)
    h = round(im.height * ANCHO / im.width)
    im = im.resize((ANCHO, h), Image.LANCZOS)
    os.makedirs(OUT, exist_ok=True)
    ruta = f"{OUT}/{nombre}.webp"
    im.save(ruta, "WEBP", quality=88, method=6)
    return {"src": ruta, "r": round(h / ANCHO, 4)}


def trozos(img, n):
    """Corta en n piezas por los n-1 huecos blancos más altos."""
    rgb = np.asarray(img.convert("RGB"))
    vacia = es_fondo(rgb, 235, 20).all(axis=1)
    filas = np.where(~vacia)[0]
    y0, y1 = filas[0], filas[-1]
    huecos, i = [], y0
    while i <= y1:
        if vacia[i]:
            j = i
            while j <= y1 and vacia[j]:
                j += 1
            huecos.append((j - i, i, j))
            i = j
        else:
            i += 1
    huecos = sorted(sorted(huecos, reverse=True)[: n - 1], key=lambda h: h[1])
    if len(huecos) < n - 1:
        raise ValueError(f"solo hay {len(huecos) + 1} piezas, se esperaban {n}")
    cortes = [y0] + [c for _, a, b in huecos for c in (a, b)] + [y1 + 1]
    return [img.crop((0, cortes[k], img.width, cortes[k + 1])) for k in range(0, len(cortes), 2)]


def main():
    fotos = {}
    if os.path.exists(FOTOS_JSON):
        fotos = json.load(open(FOTOS_JSON, encoding="utf-8"))
    solo = set(sys.argv[1:])
    for bid, capas in capas_de_la_carta().items():
        if solo and bid not in solo:
            continue
        c = f"{RAW}/completo_{bid}.png"
        if os.path.exists(c):
            fotos[f"completo_{bid}"] = guardar(quitar_fondo(Image.open(c), sombra=True), f"completo_{bid}")
            print("ok", c)
        d = f"{RAW}/{bid}.png"
        if os.path.exists(d):
            for key, pieza in zip(capas, trozos(Image.open(d), len(capas))):
                if key == "x":
                    continue
                fotos[f"{bid}.{key}"] = guardar(quitar_fondo(pieza, key in AROS, key in BLANCOS, key.startswith("barra")), f"{bid}.{key}")
            print("ok", d, len(capas), "capas")
    for nombre, keys in extras_de_la_carpeta().items():
        e = f"{RAW}/{nombre}.png"
        if os.path.exists(e) and (not solo or nombre in solo):
            for key, pieza in zip(keys, trozos(Image.open(e), len(keys))):
                if key != "x":
                    fotos[key] = guardar(quitar_fondo(pieza, key in AROS, key in BLANCOS, key not in BLANCOS), key)
            print("ok", e)
    # Raciones para picar: plato blanco, umbral estricto para no comerse el borde del plato
    for f in sorted(os.listdir(RAW)):
        if f.startswith("picar_") and f.endswith(".png"):
            k = f[:-4]
            if solo and k[6:] not in solo:
                continue
            fotos[k] = guardar(quitar_fondo(Image.open(f"{RAW}/{f}"), blanco=True), k)
            print("ok", f)
    json.dump(fotos, open(FOTOS_JSON, "w", encoding="utf-8"), indent=1)
    with open(FOTOS_JS, "w", encoding="utf-8") as f:
        f.write("window.FOTOS = " + json.dumps(fotos, indent=1) + ";\n")
    print(len(fotos), "fotos en fotos.js")


if __name__ == "__main__":
    main()
