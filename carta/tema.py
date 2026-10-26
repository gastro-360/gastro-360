# SPDX-License-Identifier: EUPL-1.2
"""Tokens de diseño (variables CSS) de un restaurante, calculados desde su marca.json.

Solo hace falta dar el fondo, el color principal y el de acento: superficies, líneas, tintas y colores de estado
se derivan de ellos y se corrigen hasta alcanzar el contraste mínimo (4,5:1 en texto, 3:1 en bordes de controles).
Un valor ausente cae al tema neutro del producto (restaurante.COLORES). El resultado se sirve como /tema.css."""
import restaurante

MIN_TEXTO = 4.5
MIN_CONTROL = 3.0


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _hex(c):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(x))) for x in c)


def _lum(c):
    f = lambda v: (v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = _lum(_rgb(a)), _lum(_rgb(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def mezcla(a, b, t):
    """a con una proporción t de b."""
    ca, cb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ca, cb)))


def con_contraste(color, fondos, minimo, hacia=None):
    """Acerca `color` a `hacia` (negro o blanco, el que más contraste dé) hasta llegar al mínimo contra todos los fondos."""
    fondos = [fondos] if isinstance(fondos, str) else fondos
    peor = lambda c: min(contraste(c, f) for f in fondos)
    if peor(color) >= minimo:
        return color
    if hacia is None:
        hacia = "#000000" if sum(contraste("#000000", f) for f in fondos) >= sum(contraste("#FFFFFF", f) for f in fondos) else "#FFFFFF"
    for i in range(1, 21):
        c = mezcla(color, hacia, i / 20)
        if peor(c) >= minimo:
            return c
    return hacia


def texto_sobre(fondo):
    """Texto (casi negro o blanco) con el mejor contraste sobre `fondo`."""
    return "#111111" if contraste("#111111", fondo) >= contraste("#FFFFFF", fondo) else "#FFFFFF"


def relleno_legible(color):
    """Color de relleno para un botón: el dado, oscurecido o aclarado lo justo para que su texto llegue a 4,5:1."""
    t = texto_sobre(color)
    return con_contraste(color, t, MIN_TEXTO, hacia="#FFFFFF" if t == "#111111" else "#000000") if contraste(color, t) < MIN_TEXTO else color


def tokens(m):
    """Diccionario {variable CSS: valor} para la marca `m` (ya completada por restaurante.completar_marca)."""
    c = m["colores"]
    fondo = c["fondo"]
    oscuro = contraste(fondo, "#FFFFFF") > contraste(fondo, "#000000")
    polo = "#FFFFFF" if oscuro else "#000000"
    superficie = c.get("superficie") or (mezcla(fondo, polo, .05) if oscuro else mezcla(fondo, "#FFFFFF", .75))
    superficie_2 = mezcla(superficie, polo, .06 if not oscuro else .07) if not c.get("superficie_2") else c["superficie_2"]
    fondos = [fondo, superficie, superficie_2]
    tinta = c.get("tinta") or mezcla(fondo, polo, .93)
    tinta = con_contraste(tinta, fondos, 12)
    tinta_2 = con_contraste(mezcla(tinta, fondo, .38), fondos, 5)
    linea = mezcla(superficie, polo, .13)
    linea_fuerte = con_contraste(mezcla(superficie, polo, .4), [superficie, superficie_2, fondo], MIN_CONTROL)
    relleno = relleno_legible(c["primario"])
    acento_relleno = relleno_legible(c["acento"])
    primario_suave = c["primario_suave"] if contraste(tinta, c["primario_suave"]) >= MIN_TEXTO else mezcla(fondo, c["primario"], .16)
    acento_suave = c["acento_suave"] if contraste(tinta, c["acento_suave"]) >= MIN_TEXTO else mezcla(fondo, c["acento"], .16)
    suaves = fondos + [primario_suave, acento_suave]
    peligro = con_contraste("#F2958B" if oscuro else "#B3261E", suaves, MIN_TEXTO)
    ok = con_contraste("#7BD18F" if oscuro else "#1B6E37", suaves, MIN_TEXTO)
    peligro_suave = mezcla(fondo, peligro, .16)
    ok_suave = mezcla(fondo, ok, .16)
    forma = {**restaurante.FORMA, **(m.get("forma") or {})}
    u = restaurante.DENSIDAD[forma["densidad"]]
    r = int(forma["radio"])
    t = {
        "--fondo": fondo, "--superficie": superficie, "--superficie-2": superficie_2,
        "--linea": linea, "--linea-fuerte": linea_fuerte,
        "--tinta": tinta, "--tinta-2": tinta_2,
        "--primario": relleno, "--sobre-primario": texto_sobre(relleno),
        "--primario-texto": con_contraste(c["primario"], suaves, MIN_TEXTO), "--primario-suave": primario_suave,
        "--acento": acento_relleno, "--sobre-acento": texto_sobre(acento_relleno),
        "--acento-texto": con_contraste(c.get("acento_texto") or c["acento"], suaves, MIN_TEXTO), "--acento-suave": acento_suave,
        "--peligro": peligro, "--peligro-suave": peligro_suave, "--sobre-peligro": texto_sobre(peligro),
        "--ok": ok, "--ok-suave": ok_suave, "--sobre-ok": texto_sobre(ok),
        "--sombra": "rgba(0,0,0,.55)" if oscuro else "rgba(20,20,20,.22)",
        "--velo": "rgba(0,0,0,.6)" if oscuro else "rgba(20,20,20,.5)",
        "--r": f"{r}px", "--r-ctl": f"{round(r * .75)}px", "--r-chip": "999px" if r >= 6 else f"{r}px",
        "--u": f"{u}px",
        "--f-titulos": m["tipografia"]["titulos"] + restaurante.RESPALDO_CJK,
        "--f-texto": m["tipografia"]["texto"] + restaurante.RESPALDO_CJK,
        "--f-mono": m["tipografia"]["mono"] + restaurante.RESPALDO_CJK,
    }
    return t, oscuro


def css(m=None):
    """Contenido de /tema.css."""
    m = m or restaurante.marca()
    t, oscuro = tokens(m)
    cuerpo = "".join(f"{k}:{v};" for k, v in t.items())
    return f":root{{{cuerpo}color-scheme:{'dark' if oscuro else 'light'}}}\n"

