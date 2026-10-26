# SPDX-License-Identifier: EUPL-1.2
"""Ocho idiomas: castellano (es, la fuente), inglés (en), catalán (ca), chino simplificado (zh), francés (fr), alemán (de),
italiano (it) y portugués europeo (pt).
Los textos de la interfaz viven en carta/i18n/<idioma>.json con claves estables (planas, con puntos). No hay traducción automática:
cada idioma lo redacta una persona. Una clave que falta en un idioma cae a castellano.

Los campos de la carta que rellena el dueño (nombre, descripción, sección…) son un texto (solo castellano) o un objeto
{"es": …, "en": …, "ca": …, "zh": …, "fr": …, "de": …, "it": …, "pt": …}; un idioma vacío cae a castellano.

Fechas, meses y números salen de tablas propias: no dependen del locale del contenedor ni del navegador."""
import datetime, json, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(BASE, "i18n")
IDIOMAS = ("es", "en", "ca", "zh", "fr", "de", "it", "pt")
FUENTE = "es"
NOMBRES = {"es": "Castellano", "en": "English", "ca": "Català", "zh": "中文", "fr": "Français", "de": "Deutsch", "it": "Italiano", "pt": "Português"}

_cache = {}


def diccionario(idioma):
    if idioma not in IDIOMAS:
        idioma = FUENTE
    if idioma not in _cache:
        with open(os.path.join(DIR, idioma + ".json"), encoding="utf-8") as f:
            _cache[idioma] = json.load(f)
    return _cache[idioma]


def t(clave, idioma=FUENTE, **p):
    """Texto de la interfaz en un idioma, con los {marcadores} rellenos (un valor que sea un campo de la carta {es, en…} sale en ese idioma).
    Cae a castellano y, si ni ahí está, devuelve la clave."""
    txt = diccionario(idioma).get(clave)
    if txt is None:
        txt = diccionario(FUENTE).get(clave, clave)
    return txt.format(**{k: tr(v, idioma) if isinstance(v, dict) else v for k, v in p.items()}) if p else txt


class Msg(ValueError):
    """Error con mensaje para una persona. str(e) sale en castellano; e.en(idioma) en el idioma de quien lo recibe."""

    def __init__(self, clave, **p):
        self.clave, self.p = clave, p
        super().__init__(t(clave, FUENTE, **p))

    def en(self, idioma):
        return t(self.clave, idioma, **self.p)


def mensaje(e, idioma):
    return e.en(idioma) if isinstance(e, Msg) else str(e)


def _calidades(cabecera):
    for parte in (cabecera or "").split(","):
        etiqueta, _, resto = parte.strip().partition(";")
        m = re.search(r"q\s*=\s*([0-9.]+)", resto)
        try:
            q = float(m.group(1)) if m else 1.0
        except ValueError:
            q = 0.0
        if etiqueta and q > 0:
            yield q, etiqueta.strip().lower()


def desde_cabecera(accept_language):
    """Idioma de la primera visita según Accept-Language (el de mayor calidad que sea uno de los ocho; si no, castellano)."""
    for _, etiqueta in sorted(_calidades(accept_language), key=lambda x: -x[0]):
        base = re.split(r"[-_]", etiqueta)[0]
        if base in IDIOMAS:
            return base
    return FUENTE


def valido(idioma):
    return idioma if idioma in IDIOMAS else None


def de_peticion(headers):
    """Idioma de una petición: X-Idioma (lo manda la interfaz con el idioma que ha elegido la persona) y, si no, Accept-Language."""
    return valido((headers.get("X-Idioma") or "").strip().lower()) or desde_cabecera(headers.get("Accept-Language"))


# ---------- campos de la carta ----------
def tr(valor, idioma=FUENTE):
    """Un campo de la carta en un idioma. Vacío en ese idioma -> castellano."""
    if isinstance(valor, dict):
        return valor.get(idioma) or valor.get(FUENTE) or ""
    return valor if isinstance(valor, str) else ""


def limpiar_campo(valor, etiqueta, maximo, vacio=False):
    """Valida un campo traducible (texto o {idioma: texto}). Devuelve un texto si solo hay castellano, o un objeto con los idiomas rellenos.
    El castellano es obligatorio salvo vacio=True."""
    if valor is None:
        valor = ""
    if isinstance(valor, str):
        valor = {FUENTE: valor}
    if not isinstance(valor, dict) or any(k not in IDIOMAS for k in valor):
        raise Msg("srv.campo_idiomas", campo=etiqueta)
    limpio = {}
    for k in IDIOMAS:
        v = valor.get(k)
        if v is None or v == "":
            continue
        if not isinstance(v, str) or len(v.strip()) > maximo:
            raise Msg("srv.texto_largo", campo=etiqueta)
        if v.strip():
            limpio[k] = v.strip()
    if not limpio.get(FUENTE):
        if limpio:
            raise Msg("srv.falta_castellano", campo=etiqueta)
        if not vacio:
            raise Msg("srv.texto_vacio", campo=etiqueta)
        return ""
    return limpio[FUENTE] if len(limpio) == 1 else limpio


# ---------- fechas y números (tablas propias) ----------
MESES = {
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
    "en": "January February March April May June July August September October November December".split(),
    "ca": "gener febrer març abril maig juny juliol agost setembre octubre novembre desembre".split(),
    "zh": [f"{i}月" for i in range(1, 13)],
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split(),
    "it": "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(),
    "pt": "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro".split(),
}
DIAS = {   # de lunes a domingo
    "es": "lunes martes miércoles jueves viernes sábado domingo".split(),
    "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(),
    "ca": "dilluns dimarts dimecres dijous divendres dissabte diumenge".split(),
    "zh": "星期一 星期二 星期三 星期四 星期五 星期六 星期日".split(),
    "fr": "lundi mardi mercredi jeudi vendredi samedi dimanche".split(),
    "de": "Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag".split(),
    "it": "lunedì martedì mercoledì giovedì venerdì sabato domenica".split(),
    "pt": "segunda-feira terça-feira quarta-feira quinta-feira sexta-feira sábado domingo".split(),
}


def mes(anio, m, idioma=FUENTE):
    """«octubre de 2026» · «October 2026» · «octubre de 2026» · «2026年10月» · «octobre 2026» · «Oktober 2026» · «ottobre 2026» · «outubro de 2026»"""
    nombre = MESES.get(idioma, MESES[FUENTE])[m - 1]
    if idioma == "zh":
        return f"{anio}年{nombre}"
    if idioma in ("en", "fr", "de", "it"):
        return f"{nombre} {anio}"
    return f"{nombre} de {anio}"


def fecha(d, idioma=FUENTE):
    """«22 de octubre de 2026» · «22 October 2026» · «22 d'octubre de 2026» · «2026年10月22日» · «22 octobre 2026» · «22. Oktober 2026»
    · «22 ottobre 2026» · «22 de outubro de 2026»"""
    if idioma == "zh":
        return f"{d.year}年{d.month}月{d.day}日"
    nombre = MESES.get(idioma, MESES[FUENTE])[d.month - 1]
    if idioma in ("en", "fr", "it"):
        return f"{d.day} {nombre} {d.year}"
    if idioma == "de":
        return f"{d.day}. {nombre} {d.year}"
    if idioma == "ca":
        return f"{d.day} {'d’' if nombre[0] in 'aeiou' else 'de '}{nombre} de {d.year}"
    return f"{d.day} de {nombre} de {d.year}"


def dia_semana(d, idioma=FUENTE):
    return DIAS.get(idioma, DIAS[FUENTE])[d.weekday()]


def hora(d):
    return f"{d.hour:02d}:{d.minute:02d}"


# Separador de miles y de decimales de cada idioma (fr: espacio fino; pt: espacio duro)
SEPARADORES = {"es": ".,", "ca": ".,", "de": ".,", "it": ".,", "en": ",.", "zh": ",.", "fr": "\u202f,", "pt": "\u00a0,"}


def numero(n, idioma=FUENTE, decimales=2):
    """1234.5 -> «1.234,50» (es, ca, de, it) · «1,234.50» (en, zh) · «1 234,50» (fr, pt)"""
    miles, coma = SEPARADORES.get(idioma, SEPARADORES[FUENTE])
    s = f"{abs(n):,.{decimales}f}"   # 1,234.50
    s = s.replace(",", "\0").replace(".", coma).replace("\0", miles)
    return ("-" if n < 0 else "") + s


def moneda(n, idioma=FUENTE):
    """5.5 -> «5,50 €» (es, ca, fr, de, it, pt) · «€5.50» (en, zh)"""
    s = numero(n, idioma)
    return f"€{s}" if idioma in ("en", "zh") else f"{s} €"
