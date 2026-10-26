# SPDX-License-Identifier: EUPL-1.2
"""Pedidos online (a domicilio y para recoger), sin pasarela de pago.

El cliente paga al recibir, con el ticket de la caja del restaurante: aquí no se registra ningún cobro, la preferencia de pago
(tarjeta o efectivo) es solo una nota logística para el repartidor y la hoja de reparto no lleva importes.

- Ajustes del dueño en <restaurante>/pedidos_online.json (fuera de git). Si no existe, se usan los de
  <restaurante>/pedidos_online.defecto.json (la demo lo trae para poder probarlo) y, si tampoco, todo desactivado.
- Estados: recibido → aceptado (con hora estimada) | rechazado (con motivo) → preparando → listo → en_reparto (solo domicilio)
  → entregado; cancelado en cualquier momento antes de entregar. La cocina solo los ve desde «aceptado».
- Seguimiento del cliente por un token aleatorio largo (no el número ni el id del pedido)."""
import datetime, html, json, os, re, secrets

import idiomas, restaurante

TIPOS = ("domicilio", "recoger")
ESTADOS = ("recibido", "aceptado", "rechazado", "preparando", "listo", "en_reparto", "entregado", "cancelado")
FINALES = ("entregado", "rechazado", "cancelado")
OCULTOS_COCINA = ("recibido", "rechazado", "cancelado")   # la cocina no ve un pedido online hasta que la sala lo acepta
PAGOS = ("tarjeta", "efectivo")
FICHERO = os.path.join(restaurante.DIR, "pedidos_online.json")
DEFECTO = os.path.join(restaurante.DIR, "pedidos_online.defecto.json")
APAGADO = {"domicilio": False, "recoger": False, "pausa": False, "dias": [0, 1, 2, 3, 4, 5, 6], "tramos": [["13:00", "16:00"], ["20:00", "23:30"]],
           "minimo": 0, "envio": 0, "cps": [], "preparacion": 30}
HORA_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
CP_RE = re.compile(r"\d{5}")


def es_online(p):
    return p.get("tipo") in TIPOS


# ---------- ajustes del dueño ----------
def _minutos(h):
    return int(h[:2]) * 60 + int(h[3:])


def validar_ajustes(d):
    """Copia limpia de los ajustes. Lanza idiomas.Msg si algo no vale."""
    if not isinstance(d, dict):
        raise idiomas.Msg("srv.online.ajustes", campo="-")
    a = dict(APAGADO)
    for k in ("domicilio", "recoger", "pausa"):
        if k in d:
            if not isinstance(d[k], bool):
                raise idiomas.Msg("srv.online.ajustes", campo=k)
            a[k] = d[k]
    dias = d.get("dias", a["dias"])
    if not isinstance(dias, list) or not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 6 for x in dias):
        raise idiomas.Msg("srv.online.ajustes", campo="dias")
    a["dias"] = sorted(set(dias))
    tramos = d.get("tramos", a["tramos"])
    if not isinstance(tramos, list) or len(tramos) > 6:
        raise idiomas.Msg("srv.online.ajustes", campo="tramos")
    limpios = []
    for t in tramos:
        if not (isinstance(t, list) and len(t) == 2 and all(isinstance(x, str) and HORA_RE.fullmatch(x) for x in t) and _minutos(t[0]) < _minutos(t[1])):
            raise idiomas.Msg("srv.online.ajustes", campo="tramos")
        limpios.append([t[0], t[1]])
    a["tramos"] = sorted(limpios)
    for k, tope in (("minimo", 999), ("envio", 99)):
        v = d.get(k, a[k])
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= tope:
            raise idiomas.Msg("srv.online.ajustes", campo=k)
        a[k] = round(float(v), 2)
    cps = d.get("cps", a["cps"])
    if isinstance(cps, str):
        cps = [x.strip() for x in re.split(r"[\s,;]+", cps) if x.strip()]
    if not isinstance(cps, list) or len(cps) > 300 or not all(isinstance(x, str) and CP_RE.fullmatch(x) for x in cps):
        raise idiomas.Msg("srv.online.ajustes", campo="cps")
    a["cps"] = sorted(set(cps))
    prep = d.get("preparacion", a["preparacion"])
    if not isinstance(prep, int) or isinstance(prep, bool) or not 5 <= prep <= 240:
        raise idiomas.Msg("srv.online.ajustes", campo="preparacion")
    a["preparacion"] = prep
    if a["domicilio"] and not a["cps"]:
        raise idiomas.Msg("srv.online.sin_zona")
    return a


def leer_ajustes():
    for ruta in (FICHERO, DEFECTO):
        try:
            with open(ruta, encoding="utf-8") as f:
                return validar_ajustes(json.load(f))
        except (OSError, ValueError):
            continue
    return dict(APAGADO)


def guardar_ajustes(d):
    a = validar_ajustes(d)
    tmp = FICHERO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(a, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FICHERO)
    return a


def en_horario(a, momento):
    """¿Cae `momento` (datetime) en un día y un tramo del horario de pedidos?"""
    if momento.weekday() not in a["dias"]:
        return False
    m = momento.hour * 60 + momento.minute
    return any(_minutos(d) <= m <= _minutos(h) for d, h in a["tramos"])


def publico(a, ahora):
    """Lo que necesita la página de pedido (sin datos internos)."""
    return {"domicilio": a["domicilio"], "recoger": a["recoger"], "pausa": a["pausa"], "minimo": a["minimo"], "envio": a["envio"],
            "cps": a["cps"], "tramos": a["tramos"], "dias": a["dias"], "preparacion": a["preparacion"],
            "abierto_ahora": en_horario(a, ahora), "disponible": (a["domicilio"] or a["recoger"]) and not a["pausa"]}


# ---------- validación del pedido online ----------
def _texto(v, clave, minimo, maximo):
    if not isinstance(v, str) or not minimo <= len(v.strip()) <= maximo:
        raise idiomas.Msg(clave)
    return " ".join(v.split())


def validar_entrega(cuerpo, a, subtotal, ahora):
    """Comprueba tipo, datos de entrega, hora y preferencia de pago contra los ajustes. Devuelve los campos que se guardan
    en el pedido. Lanza idiomas.Msg con un mensaje para el cliente."""
    tipo = cuerpo.get("tipo")
    if tipo not in TIPOS:
        raise idiomas.Msg("srv.online.tipo")
    if a["pausa"]:
        raise idiomas.Msg("srv.online.pausa")
    if not a[tipo]:
        raise idiomas.Msg("srv.online.tipo_inactivo")
    entrega = {"nombre": _texto(cuerpo.get("nombre"), "srv.online.nombre", 1, 80)}
    tel = cuerpo.get("telefono")
    if not isinstance(tel, str) or not re.fullmatch(r"\+?[0-9 .\-]{9,20}", tel.strip()) or not 9 <= sum(c.isdigit() for c in tel) <= 15:
        raise idiomas.Msg("srv.online.telefono")
    entrega["telefono"] = tel.strip()
    if tipo == "domicilio":
        entrega["direccion"] = _texto(cuerpo.get("direccion"), "srv.online.direccion", 5, 200)
        cp = cuerpo.get("cp")
        if not isinstance(cp, str) or not CP_RE.fullmatch(cp.strip()):
            raise idiomas.Msg("srv.online.cp")
        if cp.strip() not in a["cps"]:
            raise idiomas.Msg("srv.online.fuera_zona", cp=cp.strip())
        entrega["cp"] = cp.strip()
    hora = cuerpo.get("hora") or "asap"
    if hora == "asap":
        if not en_horario(a, ahora):
            raise idiomas.Msg("srv.online.cerrado_ahora")
    else:
        if not isinstance(hora, str) or not HORA_RE.fullmatch(hora):
            raise idiomas.Msg("srv.online.hora")
        momento = ahora.replace(hour=int(hora[:2]), minute=int(hora[3:]), second=0, microsecond=0)
        if not en_horario(a, momento):
            raise idiomas.Msg("srv.online.fuera_horario")
        if momento < ahora + datetime.timedelta(minutes=a["preparacion"]):
            raise idiomas.Msg("srv.online.hora_pronto", minutos=a["preparacion"])
    pago = cuerpo.get("pago")
    if pago not in PAGOS:
        raise idiomas.Msg("srv.online.pago")
    cambio = cuerpo.get("cambio") or ""
    if not isinstance(cambio, str) or len(cambio.strip()) > 60:
        raise idiomas.Msg("srv.online.cambio")
    if subtotal < a["minimo"]:
        raise idiomas.Msg("srv.online.minimo", minimo=f"{a['minimo']:.2f} €")
    return {"tipo": tipo, "entrega": entrega, "hora": hora, "pago": pago, "cambio": cambio.strip() if pago == "efectivo" else "",
            "envio": a["envio"] if tipo == "domicilio" else 0.0, "seguimiento": secrets.token_urlsafe(24)}


# ---------- estados ----------
def siguientes(p):
    """Estados a los que puede pasar un pedido online desde el actual (incluye volver un paso atrás para deshacer)."""
    dom = p.get("tipo") == "domicilio"
    return {"recibido": ("aceptado", "rechazado", "cancelado"),
            "aceptado": ("preparando", "cancelado"),
            "preparando": ("listo", "aceptado", "cancelado"),
            "listo": (("en_reparto",) if dom else ("entregado",)) + ("preparando", "cancelado"),
            "en_reparto": ("entregado", "listo", "cancelado"),
            "entregado": ("en_reparto",) if dom else ("listo",),
            }.get(p.get("estado"), ())


def cambiar_estado(p, estado, cuerpo, ahora):
    """Aplica el cambio a un pedido online (en el sitio). Lanza idiomas.Msg si no vale."""
    if estado not in ESTADOS or estado not in siguientes(p):
        raise idiomas.Msg("srv.online.transicion")
    if estado == "aceptado" and p["estado"] == "recibido":
        minutos = cuerpo.get("minutos")
        if not isinstance(minutos, int) or isinstance(minutos, bool) or not 1 <= minutos <= 240:
            raise idiomas.Msg("srv.online.minutos")
        base = ahora
        if p.get("hora") not in (None, "asap"):   # programado: la hora estimada es la pedida si da tiempo
            pedida = datetime.datetime.fromtimestamp(p["creado"]).replace(hour=int(p["hora"][:2]), minute=int(p["hora"][3:]), second=0, microsecond=0)
            base = max(ahora, pedida - datetime.timedelta(minutes=minutos))
        p["hora_estimada"] = (base + datetime.timedelta(minutes=minutos)).strftime("%H:%M")
    if estado in ("rechazado", "cancelado"):
        p["motivo"] = _texto(cuerpo.get("motivo"), "srv.online.motivo", 2, 160)
    p["estado"] = estado
    p["t"][estado] = ahora.timestamp()


MOTIVO_CADUCADO = "sin aceptar"


def limite_aceptar(p, cambio_dia):
    """Hasta cuándo puede seguir un pedido en «recibido»: su hora programada o, si es «lo antes posible», el final de su día
    de servicio (el día siguiente a la hora de cambio de día)."""
    if p.get("hora") not in (None, "asap"):
        return datetime.datetime.fromtimestamp(p["creado"]).replace(hour=int(p["hora"][:2]), minute=int(p["hora"][3:]), second=0, microsecond=0)
    return datetime.datetime.fromisoformat(p["fecha"]) + datetime.timedelta(days=1, hours=cambio_dia)


def caducar(pedidos, ahora, cambio_dia):
    """Los online que nadie aceptó a tiempo pasan solos a «cancelado» (motivo «sin aceptar»). Cambia la lista en el sitio;
    devuelve cuántos. Así entran en el archivado normal de los terminados."""
    n = 0
    for p in pedidos:
        if es_online(p) and p.get("estado") == "recibido":
            limite = limite_aceptar(p, cambio_dia)
            if ahora > limite:
                p["estado"], p["motivo"] = "cancelado", MOTIVO_CADUCADO
                p["t"]["cancelado"] = limite.timestamp()
                n += 1
    return n


# ---------- lo que ve el cliente ----------
def importe_estimado(p):
    return round(p.get("total", 0) + p.get("envio", 0), 2)


def para_seguimiento(p):
    """Resumen del pedido para su página de seguimiento: sin teléfono ni dirección."""
    return {"numero": p["numero"], "tipo": p["tipo"], "estado": p["estado"], "hora": p.get("hora", "asap"),
            "hora_estimada": p.get("hora_estimada", ""), "motivo": p.get("motivo", ""), "pago": p.get("pago", ""),
            "lineas": [{k: l.get(k) for k in ("n", "cant", "precio", "sin", "extra")} for l in p["lineas"]],
            "subtotal": p["total"], "envio": p.get("envio", 0), "importe_estimado": importe_estimado(p), "creado": p["creado"]}


def sin_secretos(p):
    """Pedido (de mesa u online) para la cocina y para las respuestas de cambio de estado: sin tokens ni datos de entrega."""
    return {k: v for k, v in p.items() if k not in ("seguimiento", "token", "entrega")}


def para_sala(p):
    """Pedido online para el backoffice (sin el token de seguimiento)."""
    return {k: v for k, v in p.items() if k not in ("seguimiento", "token")}


# ---------- hoja de reparto (imprimible, sin importes) ----------
def _nombre(v, idioma):
    return idiomas.tr(v, idioma) if isinstance(v, dict) else str(v)


def hoja_reparto(p, idioma):
    """HTML imprimible para el repartidor: dirección, teléfono, platos y preferencia de pago. Nunca lleva importes:
    se cobra con el ticket de la caja del restaurante."""
    T = lambda k, **kw: html.escape(idiomas.t(k, idioma, **kw))
    e = p.get("entrega") or {}
    tel = e.get("telefono", "")
    filas = []
    for l in p["lineas"]:
        det = []
        if l.get("sin"):
            det.append(T("cocina.sin") + " " + html.escape(", ".join(_nombre(x, idioma) for x in l["sin"])))
        if l.get("extra"):
            det.append(T("cocina.extra") + " " + html.escape(", ".join(_nombre(x, idioma) for x in l["extra"])))
        filas.append(f"<li><b>{int(l.get('cant', 1))}×</b> {html.escape(_nombre(l.get('n', ''), idioma))}" + (f"<small>{' · '.join(det)}</small>" if det else "") + "</li>")
    hora = T("reparto.asap") if p.get("hora", "asap") == "asap" else T("reparto.para", hora=p["hora"])
    if p.get("hora_estimada"):
        hora += " · " + T("reparto.estimada", hora=p["hora_estimada"])
    pago = T("reparto.pago." + p.get("pago", "tarjeta")) + (f" · {T('reparto.cambio')}: {html.escape(p['cambio'])}" if p.get("cambio") else "")
    destino = (f"<dt>{T('reparto.direccion')}</dt><dd>{html.escape(e.get('direccion', ''))} · {html.escape(e.get('cp', ''))}</dd>"
               if p.get("tipo") == "domicilio" else f"<dt>{T('reparto.direccion')}</dt><dd>{T('reparto.recoger')}</dd>")
    nota = f"<dt>{T('reparto.nota')}</dt><dd>{html.escape(p['nota'])}</dd>" if p.get("nota") else ""
    return f"""<!doctype html>
<html lang="{html.escape(idioma)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{T('reparto.titulo', numero=p['numero'])}</title>
<style>body{{font:16px/1.4 system-ui,sans-serif;margin:24px;color:#111;background:#fff}}h1{{font-size:22px;margin:0 0 12px}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;margin:0 0 16px}}dt{{font-weight:700}}dd{{margin:0}}
ul{{padding-left:0;list-style:none}}li{{padding:6px 0;border-bottom:1px solid #ddd}}li small{{display:block;color:#444}}
.cobrar{{border:2px solid #111;padding:10px 14px;font-weight:700;font-size:18px}}@media print{{button{{display:none}}}}</style></head>
<body><h1>{T('reparto.titulo', numero=p['numero'])}</h1>
<dl><dt>{T('reparto.cliente')}</dt><dd>{html.escape(e.get('nombre', ''))}</dd>
<dt>{T('reparto.telefono')}</dt><dd><a href="tel:{html.escape(re.sub(r'[^0-9+]', '', tel))}">{html.escape(tel)}</a></dd>
{destino}<dt>{T('reparto.hora')}</dt><dd>{hora}</dd>{nota}<dt>{T('reparto.pago')}</dt><dd>{pago}</dd></dl>
<h2>{T('reparto.platos')}</h2><ul>{''.join(filas)}</ul>
<p class="cobrar">{T('reparto.cobrar')}</p>
<button type="button" id="imprimir">{T('reparto.imprimir')}</button>
<script>document.getElementById('imprimir').addEventListener('click',()=>window.print())</script>
</body></html>"""
