# SPDX-License-Identifier: EUPL-1.2
"""Los 14 alérgenos de declaración obligatoria (Reglamento (UE) 1169/2011, anexo II): lista cerrada, única fuente.
Los datos están en alergenos.json (identificador estable en inglés y nombre por idioma) y los iconos en iconos_alergenos/<id>.svg.

Qué guarda cada plato en «alergenos» (tres situaciones distintas):
  lista con identificadores   el restaurante marca lo que lleva
  lista vacía []              el restaurante confirma que no lleva ninguno («sin alérgenos declarados»)
  ausente o null              todavía sin revisar (valor por defecto de los platos existentes y nuevos)"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
ICONOS = os.path.join(BASE, "iconos_alergenos")
with open(os.path.join(BASE, "alergenos.json"), encoding="utf-8") as _f:
    _DATOS = json.load(_f)

LISTA = tuple(a["id"] for a in _DATOS["alergenos"])    # el orden de esta lista es el de la carta
TEXTOS = _DATOS["textos"]
IDIOMA = "es"
AVISO = TEXTOS[IDIOMA]["aviso"]                        # fijo: el restaurante no puede quitarlo ni cambiarlo

MARCADOS, SIN_DECLARAR, SIN_REVISAR = "marcados", "sin_declarar", "sin_revisar"


def nombre(id_, idioma=IDIOMA):
    for a in _DATOS["alergenos"]:
        if a["id"] == id_:
            return a["nombre"].get(idioma) or a["nombre"][IDIOMA]
    raise KeyError(id_)


def texto(clave, idioma=IDIOMA):
    return TEXTOS.get(idioma, TEXTOS[IDIOMA]).get(clave) or TEXTOS[IDIOMA][clave]


def icono(id_):
    with open(os.path.join(ICONOS, id_ + ".svg"), encoding="utf-8") as f:
        return "".join(l for l in f.read().splitlines() if not l.startswith("<!--")).strip()


def limpiar(valor, etiqueta="plato"):
    """Valida lo que llega del backoffice. Devuelve la lista limpia (en el orden de la carta), [] o None (sin revisar).
    Lanza ValueError con un mensaje para el dueño si hay algo fuera de la lista de 14."""
    if valor is None:
        return None
    if not isinstance(valor, list):
        raise ValueError(f"{etiqueta}: alérgenos no válidos")
    for x in valor:
        if not isinstance(x, str) or x not in LISTA:
            raise ValueError(f"{etiqueta}: «{x}» no es uno de los 14 alérgenos de declaración obligatoria")
    return [a for a in LISTA if a in valor]


def estado(valor):
    if valor is None:
        return SIN_REVISAR
    return MARCADOS if valor else SIN_DECLARAR


def publicos():
    """Lo que necesitan las páginas (carta, cocina, backoffice): lista con nombre e icono, y los textos fijos. Se sirve como alergenos.js."""
    return {"lista": [{"id": a["id"], "n": a["nombre"], "svg": icono(a["id"])} for a in _DATOS["alergenos"]],
            "textos": TEXTOS, "idioma": IDIOMA}
