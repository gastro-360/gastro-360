# SPDX-License-Identifier: EUPL-1.2
"""Genera fotos MARCADORAS (degradados con un icono, sin texto ni marca) para un restaurante, a partir de su datos.json.

Sirven para ver la carta completa antes de tener fotos reales y para la demo. Todo se dibuja aquí: no se copia ninguna foto.
  python fotos_marcadoras.py              (restaurante activo: variable RESTAURANTE)
Escribe fotos/*.webp, fotos.json, fotos.js y marca/logo.png. Necesita Pillow (ya está en la imagen de Docker). La salida es
determinista: misma carta, mismos bytes.
"""
import json, math, os

from PIL import Image, ImageDraw

import restaurante

ANCHO = 800
SS = 2          # supermuestreo para bordes suaves
PAN = "#D9A857"
FORMAS = {"leaf": "rombo", "sauce": "onda", "onion": "aro", "olives": "aro", "coins": "aro"}   # el resto: puntos


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mezcla(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def banda(color, r, forma="puntos", cupula=False):
    """Una capa: banda redondeada con degradado vertical y un icono repetido. r = alto / ancho."""
    w, h = ANCHO * SS, max(8, round(ANCHO * SS * r))
    base = rgb(color)
    claro, oscuro = mezcla(base, (255, 255, 255), .35), mezcla(base, (0, 0, 0), .35)
    grad = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(grad)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=mezcla(claro, oscuro, y / max(1, h - 1)) + (255,))
    icono = ImageDraw.Draw(grad)
    paso, rad = w // 7, max(3, h // 5)
    for k in range(6):
        cx, cy = paso // 2 + k * paso + (paso // 2 if k % 2 else 0) * 0, h // 2
        tono = mezcla(base, (255, 255, 255), .55) + (170,)
        if forma == "rombo":
            icono.polygon([(cx, cy - rad), (cx + rad, cy), (cx, cy + rad), (cx - rad, cy)], fill=tono)
        elif forma == "aro":
            icono.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=tono, width=max(2, rad // 3))
        elif forma == "onda":
            icono.arc([cx - rad, cy - rad, cx + rad, cy + rad], 0, 180, fill=tono, width=max(2, rad // 3))
        else:
            icono.ellipse([cx - rad // 2, cy - rad // 2, cx + rad // 2, cy + rad // 2], fill=tono)
    mascara = Image.new("L", (w, h), 0)
    m = ImageDraw.Draw(mascara)
    if cupula:
        m.pieslice([0, 0, w, h * 2], 180, 360, fill=255)
    else:
        m.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=255)
    grad.putalpha(mascara)
    return grad.resize((ANCHO, round(h / SS)), Image.LANCZOS)


def apila(capas):
    """Capas de arriba abajo: cada una tapa un tercio de la de debajo."""
    alto = sum(c.height * .66 for c in capas[:-1]) + capas[-1].height
    lienzo = Image.new("RGBA", (ANCHO, round(alto)), (0, 0, 0, 0))
    y = 0
    for c in capas:
        lienzo.alpha_composite(c, (0, round(y)))
        y += c.height * .66
    return lienzo


def racion(color):
    w = ANCHO * SS
    lienzo = Image.new("RGBA", (w, round(w * .72)), (0, 0, 0, 0))
    d = ImageDraw.Draw(lienzo)
    d.ellipse([0, w * .04, w - 1, w * .68], fill=(238, 238, 238, 255))
    d.ellipse([w * .06, w * .1, w * .94, w * .62], fill=(250, 250, 250, 255))
    monton = banda(color, .3, "puntos", cupula=True).resize((round(w * .6), round(w * .3)), Image.LANCZOS)
    lienzo.alpha_composite(monton, (round(w * .2), round(w * .16)))
    return lienzo.resize((ANCHO, round(lienzo.height / SS)), Image.LANCZOS)


def logo(color):
    lado = 512 * SS
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    base = rgb(color)
    for y in range(lado):
        ImageDraw.Draw(img).line([(0, y), (lado, y)], fill=mezcla(mezcla(base, (255, 255, 255), .25), mezcla(base, (0, 0, 0), .4), y / lado) + (255,))
    mascara = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, lado - 1, lado - 1], fill=255)
    img.putalpha(mascara)
    d = ImageDraw.Draw(img)
    c, rad = lado / 2, lado * .22
    d.arc([c - rad, c - rad, c + rad, c + rad], 200, 340, fill=(255, 255, 255, 230), width=lado // 28) 
    d.ellipse([c - lado * .05, c - lado * .02, c + lado * .05, c + lado * .08], fill=(255, 255, 255, 230))
    return img.resize((512, 512), Image.LANCZOS)


def guardar(im, nombre, carpeta, fotos):
    os.makedirs(carpeta, exist_ok=True)
    im.save(os.path.join(carpeta, nombre + ".webp"), "WEBP", quality=82, method=6)
    fotos[nombre] = {"src": f"fotos/{nombre}.webp", "r": round(im.height / im.width, 4)}


def generar(dir_restaurante):
    with open(os.path.join(dir_restaurante, "datos.json"), encoding="utf-8") as f:
        datos = json.load(f)
    ing, carpeta, fotos = datos["ingredientes"], os.path.join(dir_restaurante, "fotos"), {}
    pan_arriba = banda(PAN, .17, cupula=True)
    pan_abajo = banda("#C99747", .09)
    for p in datos.get("platos") or []:
        capas = [pan_arriba]
        guardar(pan_arriba, f"{p['id']}.barra_arriba", carpeta, fotos)
        for k in reversed(p.get("i") or []):
            x = ing[k]
            capa = banda(x["c"], x.get("h", 8) / 180, FORMAS.get(x.get("s"), "puntos"))
            guardar(capa, f"{p['id']}.{k}", carpeta, fotos)
            capas.append(capa)
        guardar(pan_abajo, f"{p['id']}.barra_abajo", carpeta, fotos)
        capas.append(pan_abajo)
        guardar(apila(capas), f"completo_{p['id']}", carpeta, fotos)
    for r in datos.get("picar") or []:
        guardar(racion(r["c"]), f"picar_{r['id']}", carpeta, fotos)
    fotos = dict(sorted(fotos.items()))
    with open(os.path.join(dir_restaurante, "fotos.json"), "w", encoding="utf-8") as f:
        json.dump(fotos, f, indent=1)
    with open(os.path.join(dir_restaurante, "fotos.js"), "w", encoding="utf-8") as f:
        f.write("window.FOTOS = " + json.dumps(fotos, indent=1) + ";\n")
    with open(os.path.join(dir_restaurante, "marca.json"), encoding="utf-8") as f:
        m = json.load(f)
    os.makedirs(os.path.join(dir_restaurante, "marca"), exist_ok=True)
    logo(m.get("colores", {}).get("acento", "#E0A458")).save(os.path.join(dir_restaurante, "marca", m["logo"]), "PNG")
    return len(fotos)


if __name__ == "__main__":
    print(generar(restaurante.DIR), "fotos marcadoras en", restaurante.DIR)
