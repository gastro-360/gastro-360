# SPDX-License-Identifier: EUPL-1.2
"""Crea un restaurante nuevo (vacío, con un ejemplo) en restaurantes/<slug>/ a partir de la plantilla.

  python nuevo_restaurante.py demo
  python nuevo_restaurante.py bar-pepe --nombre "Bar Pepe" --color "#2A6F4F"

Después: editar restaurantes/<slug>/marca.json y marca/ (logo), y arrancar con
  RESTAURANTE=<slug> python preparar_netlify.py && RESTAURANTE=<slug> python servidor.py
Solo biblioteca estándar: el logo provisional es un PNG que se dibuja aquí mismo.
"""
import argparse, json, os, re, struct, sys, zlib

RAIZ = os.environ.get("CARTA_RESTAURANTES") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "restaurantes")
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")

# Un plato montable y una ración de ejemplo, para que la carta no salga vacía (el local los cambia o borra en el backoffice).
DATOS = {
    "version": 1,
    "gruposExtra": [["quesos", "Quesos"], ["verduras", "Verduras"]],
    "ingredientes": {
        "jamon": {"n": "Jamón", "cat": "embutidos", "p": None, "s": "ham", "h": 8, "c": "#D98B8B"},
        "queso": {"n": "Queso", "cat": "quesos", "p": 0.8, "s": "cheeseFlat", "h": 5, "c": "#F2D16B"},
        "lechuga": {"n": "Lechuga", "cat": "verduras", "p": 0.5, "s": "leaf", "h": 7, "c": "#86BF4C"},
    },
    "platos": [
        {"id": "ejemplo", "sec": "Platos", "pan": "barra", "p": 4.5, "i": ["lechuga", "jamon", "queso"],
         "n": "Plato de ejemplo", "d": "Jamón, queso y lechuga. Cámbialo desde el backoffice."},
    ],
    "picar": [{"id": "racion_ejemplo", "n": "Ración de ejemplo", "p": 3.0, "c": "#D9A040"}],
    "mesas": [],
    "urlQR": "",
}


def logo_png(color, lado=256):
    """PNG de un círculo liso del color de la marca, sin dependencias."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    c = (lado - 1) / 2
    filas = bytearray()
    for y in range(lado):
        filas.append(0)
        for x in range(lado):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            a = max(0, min(255, int((c - d) * 255)))   # borde suavizado de un píxel
            filas += bytes((r, g, b, a))

    def trozo(tipo, datos):
        t = tipo + datos
        return struct.pack(">I", len(datos)) + t + struct.pack(">I", zlib.crc32(t) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 6, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(bytes(filas), 9)) + trozo(b"IEND", b""))


def crear(slug, nombre=None, color="#F0B43A", raiz=RAIZ):
    if not SLUG.fullmatch(slug):
        raise ValueError(f"Nombre no válido: {slug!r} (solo minúsculas, números, guiones)")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise ValueError(f"Color no válido: {color!r} (formato #RRGGBB)")
    carpeta = os.path.join(raiz, slug)
    if os.path.exists(carpeta):
        raise ValueError(f"Ya existe {carpeta}; no se toca")
    nombre = (nombre or slug.replace("-", " ").replace("_", " ").title()).strip()
    os.makedirs(os.path.join(carpeta, "marca"))
    os.makedirs(os.path.join(carpeta, "fotos"))
    marca = {"nombre": nombre, "nombre_corto": nombre, "nombre_resalte": nombre.rsplit(" ", 1)[-1],
             "descripcion": f"Carta interactiva de {nombre}", "logo": "logo_provisional.png",
             "lema": "Carta interactiva", "colores": {"acento": color}}
    escribir = {
        "marca.json": json.dumps(marca, ensure_ascii=False, indent=1) + "\n",
        "datos.json": json.dumps(DATOS, ensure_ascii=False, indent=1),
        "datos.js": "window.DATOS = " + json.dumps(DATOS, ensure_ascii=False) + ";\n",
        "fotos.json": "{}",
        "fotos.js": "window.FOTOS = {};\n",
    }
    for archivo, contenido in escribir.items():
        with open(os.path.join(carpeta, archivo), "w", encoding="utf-8") as f:
            f.write(contenido)
    with open(os.path.join(carpeta, "marca", "logo_provisional.png"), "wb") as f:
        f.write(logo_png(color))
    return carpeta


def main():
    ap = argparse.ArgumentParser(description="Crea un restaurante nuevo en restaurantes/<slug>/")
    ap.add_argument("slug", help="nombre de la carpeta: minúsculas, números y guiones (p. ej. bar-pepe)")
    ap.add_argument("--nombre", help="nombre que verá el cliente (por defecto sale del slug)")
    ap.add_argument("--color", default="#F0B43A", help="color de acento #RRGGBB (y del logo provisional)")
    a = ap.parse_args()
    try:
        carpeta = crear(a.slug, a.nombre, a.color)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Restaurante creado en {carpeta}\nSiguiente: cambia marca.json y marca/ (logo) y arráncalo con:\n"
          f"  RESTAURANTE={a.slug} python preparar_netlify.py && RESTAURANTE={a.slug} python servidor.py")


if __name__ == "__main__":
    main()
