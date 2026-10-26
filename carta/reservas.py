# SPDX-License-Identifier: EUPL-1.2
"""Reservas de mesa con aforo por tramos (sin plano de mesas).

- Ajustes del dueño en <restaurante>/reservas.json (fuera de git). Si no existe, los de <restaurante>/reservas.defecto.json
  (la demo lo trae para poder probarlo) y, si tampoco, todo desactivado.
- Aforo: un máximo de comensales por tramo (cada `tramo` minutos) dentro del horario de llegadas de cada día de la semana.
  Cuentan las reservas solicitadas, confirmadas y sentadas.
- Modo «automatico»: si cabe, la reserva nace «confirmada». Modo «manual»: nace «solicitada» y la sala la acepta o rechaza.
- Estados: solicitada → confirmada | rechazada (con motivo) → sentada (con mesa opcional) | no_presentada; cancelada (por el cliente
  con su enlace o por el restaurante). Solas: una solicitada sin respuesta pasa a rechazada («sin respuesta») al llegar su hora;
  una confirmada pasa a no_presentada `no_presentada` minutos después de su hora.
- El cliente ve su reserva por un token aleatorio largo (no el id), sin el teléfono.
- Las reservas se guardan en <restaurante>/reservas_datos.json (fuera de git). Pendiente: borrado automático de los datos personales a N días."""
import datetime, json, os, re, secrets

import idiomas, restaurante

MODOS = ("automatico", "manual")
ESTADOS = ("solicitada", "confirmada", "rechazada", "sentada", "no_presentada", "cancelada")
ACTIVAS = ("solicitada", "confirmada", "sentada")   # ocupan aforo
FICHERO = os.path.join(restaurante.DIR, "reservas.json")
DEFECTO = os.path.join(restaurante.DIR, "reservas.defecto.json")
DATOS = os.path.join(restaurante.DIR, "reservas_datos.json")
TRAMOS = (15, 20, 30, 60)
APAGADO = {"activo": False, "modo": "manual", "tramo": 30, "aforo": 20, "max_reserva": 8,
           "horario": [[["13:00", "15:30"], ["20:00", "22:30"]]] * 7, "cerrados": [],
           "antelacion_min": 60, "antelacion_max": 30, "no_presentada": 20}
HORA_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
FECHA_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MOTIVO_SIN_RESPUESTA = "sin respuesta"
MOTIVO_CLIENTE = "cancelada por el cliente"


def _minutos(h):
    return int(h[:2]) * 60 + int(h[3:])


def _hora(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _fecha(v):
    if not isinstance(v, str) or not FECHA_RE.fullmatch(v):
        raise ValueError
    return datetime.date.fromisoformat(v)


def _entero(d, a, k, minimo, maximo):
    v = d.get(k, a[k])
    if not isinstance(v, int) or isinstance(v, bool) or not minimo <= v <= maximo:
        raise idiomas.Msg("srv.reservas.ajustes", campo=k)
    return v


# ---------- ajustes del dueño ----------
def validar_ajustes(d):
    """Copia limpia de los ajustes. Lanza idiomas.Msg si algo no vale."""
    if not isinstance(d, dict):
        raise idiomas.Msg("srv.reservas.ajustes", campo="-")
    a = dict(APAGADO)
    if "activo" in d:
        if not isinstance(d["activo"], bool):
            raise idiomas.Msg("srv.reservas.ajustes", campo="activo")
        a["activo"] = d["activo"]
    modo = d.get("modo", a["modo"])
    if modo not in MODOS:
        raise idiomas.Msg("srv.reservas.ajustes", campo="modo")
    a["modo"] = modo
    tramo = d.get("tramo", a["tramo"])
    if tramo not in TRAMOS or isinstance(tramo, bool):
        raise idiomas.Msg("srv.reservas.ajustes", campo="tramo")
    a["tramo"] = tramo
    a["aforo"] = _entero(d, a, "aforo", 1, 500)
    a["max_reserva"] = _entero(d, a, "max_reserva", 1, 100)
    a["antelacion_min"] = _entero(d, a, "antelacion_min", 0, 7 * 24 * 60)
    a["antelacion_max"] = _entero(d, a, "antelacion_max", 1, 365)
    a["no_presentada"] = _entero(d, a, "no_presentada", 5, 240)
    horario = d.get("horario", a["horario"])
    if not isinstance(horario, list) or len(horario) != 7:
        raise idiomas.Msg("srv.reservas.ajustes", campo="horario")
    limpio = []
    for dia in horario:
        if not isinstance(dia, list) or len(dia) > 6:
            raise idiomas.Msg("srv.reservas.ajustes", campo="horario")
        tramos = []
        for t in dia:
            if not (isinstance(t, list) and len(t) == 2 and all(isinstance(x, str) and HORA_RE.fullmatch(x) for x in t)
                    and _minutos(t[0]) < _minutos(t[1])):
                raise idiomas.Msg("srv.reservas.ajustes", campo="horario")
            tramos.append([t[0], t[1]])
        limpio.append(sorted(tramos))
    a["horario"] = limpio
    cerrados = d.get("cerrados", a["cerrados"])
    if isinstance(cerrados, str):
        cerrados = [x.strip() for x in re.split(r"[\s,;]+", cerrados) if x.strip()]
    try:
        if not isinstance(cerrados, list) or len(cerrados) > 366:
            raise ValueError
        a["cerrados"] = sorted({_fecha(x).isoformat() for x in cerrados})
    except (ValueError, TypeError):
        raise idiomas.Msg("srv.reservas.ajustes", campo="cerrados")
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
    _escribir(FICHERO, a)
    return a


def _escribir(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)


# ---------- reservas guardadas ----------
def leer():
    try:
        with open(DATOS, encoding="utf-8") as f:
            r = json.load(f)
        return r if isinstance(r, list) else []
    except (OSError, ValueError):
        return []


def guardar(reservas):
    _escribir(DATOS, reservas)


def momento(r):
    return datetime.datetime.fromisoformat(r["fecha"] + "T" + r["hora"])


def caducar(reservas, ahora, a):
    """Cambios solos (en el sitio): solicitada sin respuesta al llegar su hora → rechazada; confirmada X minutos después de su hora
    sin sentar → no_presentada. Devuelve cuántas cambian."""
    n = 0
    for r in reservas:
        m = momento(r)
        if r["estado"] == "solicitada" and ahora >= m:
            r["estado"], r["motivo"] = "rechazada", MOTIVO_SIN_RESPUESTA
            r["t"]["rechazada"] = m.timestamp()
            n += 1
        elif r["estado"] == "confirmada" and ahora >= fin_cortesia(r, a):
            r["estado"] = "no_presentada"
            r["t"]["no_presentada"] = fin_cortesia(r, a).timestamp()
            n += 1
    return n


# ---------- tramos y aforo ----------
def tramos_del_dia(a, dia):
    """Horas de llegada de un día (date): cada `tramo` minutos dentro de cada franja, la última antes del cierre."""
    if dia.isoformat() in a["cerrados"]:
        return []
    horas = []
    for desde, hasta in a["horario"][dia.weekday()]:
        m = _minutos(desde)
        while m < _minutos(hasta):
            horas.append(_hora(m))
            m += a["tramo"]
    return sorted(set(horas))


def ocupados(reservas, fecha, hora, sin=None):
    return sum(r["comensales"] for r in reservas if r["fecha"] == fecha and r["hora"] == hora and r["estado"] in ACTIVAS and r["id"] != sin)


def libres_del_dia(a, reservas, dia, ahora):
    """[{hora, libres}] de los tramos que aún se pueden reservar ese día (antelación mínima y máxima incluidas)."""
    if not dentro_de_antelacion_dia(a, dia, ahora):
        return []
    fuera = []
    for h in tramos_del_dia(a, dia):
        m = datetime.datetime.combine(dia, datetime.time(int(h[:2]), int(h[3:])))
        if m < ahora + datetime.timedelta(minutes=a["antelacion_min"]):
            continue
        fuera.append({"hora": h, "libres": max(0, a["aforo"] - ocupados(reservas, dia.isoformat(), h))})
    return fuera


def dentro_de_antelacion_dia(a, dia, ahora):
    return ahora.date() <= dia <= ahora.date() + datetime.timedelta(days=a["antelacion_max"])


def publico(a, ahora):
    """Lo que necesita la página de reservar (sin datos internos)."""
    return {"activo": a["activo"], "max_reserva": a["max_reserva"], "antelacion_max": a["antelacion_max"],
            "hoy": ahora.date().isoformat(), "hasta": (ahora.date() + datetime.timedelta(days=a["antelacion_max"])).isoformat()}


# ---------- nueva reserva ----------
def _texto(v, clave, minimo, maximo):
    if not isinstance(v, str) or not minimo <= len(v.strip()) <= maximo:
        raise idiomas.Msg(clave)
    return " ".join(v.split())


def validar(cuerpo, a, reservas, ahora):
    """Comprueba la petición contra los ajustes y el aforo. Devuelve la reserva nueva (sin guardar). Lanza idiomas.Msg."""
    if not a["activo"]:
        raise idiomas.Msg("srv.reservas.inactivo")
    try:
        dia = _fecha(cuerpo.get("fecha"))
    except (ValueError, TypeError):
        raise idiomas.Msg("srv.reservas.fecha")
    hora = cuerpo.get("hora")
    if not isinstance(hora, str) or not HORA_RE.fullmatch(hora):
        raise idiomas.Msg("srv.reservas.hora")
    if not dentro_de_antelacion_dia(a, dia, ahora):
        raise idiomas.Msg("srv.reservas.fecha_fuera", dias=a["antelacion_max"])
    if hora not in tramos_del_dia(a, dia):
        raise idiomas.Msg("srv.reservas.cerrado")
    m = datetime.datetime.combine(dia, datetime.time(int(hora[:2]), int(hora[3:])))
    if m < ahora + datetime.timedelta(minutes=a["antelacion_min"]):
        raise idiomas.Msg("srv.reservas.pronto", minutos=a["antelacion_min"])
    n = cuerpo.get("comensales")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= a["max_reserva"]:
        raise idiomas.Msg("srv.reservas.comensales", maximo=a["max_reserva"])
    nombre = _texto(cuerpo.get("nombre"), "srv.online.nombre", 1, 80)
    tel = cuerpo.get("telefono")
    if not isinstance(tel, str) or not re.fullmatch(r"\+?[0-9 .\-]{9,20}", tel.strip()) or not 9 <= sum(c.isdigit() for c in tel) <= 15:
        raise idiomas.Msg("srv.online.telefono")
    email = cuerpo.get("email") or ""
    if not isinstance(email, str) or len(email) > 120 or (email.strip() and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip())):
        raise idiomas.Msg("srv.reservas.email")
    nota = cuerpo.get("nota") or ""
    if not isinstance(nota, str) or len(nota) > 300:
        raise idiomas.Msg("srv.reservas.nota")
    if ocupados(reservas, dia.isoformat(), hora) + n > a["aforo"]:
        raise idiomas.Msg("srv.reservas.lleno")
    estado = "confirmada" if a["modo"] == "automatico" else "solicitada"
    t = ahora.timestamp()
    return {"id": secrets.token_urlsafe(9), "fecha": dia.isoformat(), "hora": hora, "comensales": n, "nombre": nombre,
            "telefono": tel.strip(), "email": email.strip(), "nota": " ".join(nota.split()), "estado": estado, "motivo": "", "mesa": "",
            "creado": t, "t": {estado: t}, "token": secrets.token_urlsafe(24)}


# ---------- estados ----------
def fin_cortesia(r, a):
    """Hora a partir de la cual una confirmada sin sentar pasa sola a no_presentada (su hora más la cortesía)."""
    return momento(r) + datetime.timedelta(minutes=a["no_presentada"])


def siguientes(r, a=None, ahora=None):
    """Estados a los que puede pasar una reserva desde la sala (incluye deshacer un «sentada» o un «no presentada»).
    Con `a` y `ahora`, solo los que valen en ese momento: «no presentada» no antes de su hora, y volver a «confirmada»
    no después de su hora más la cortesía (`caducar` lo desharía; lo que vale entonces es «sentada»)."""
    base = {"solicitada": ("confirmada", "rechazada", "cancelada"),
            "confirmada": ("sentada", "no_presentada", "cancelada"),
            "sentada": ("confirmada",),
            "no_presentada": ("sentada", "confirmada"),
            }.get(r.get("estado"), ())
    if a is None or ahora is None:
        return base
    return tuple(e for e in base if not _vetado(r, e, a, ahora))


def _vetado(r, estado, a, ahora):
    """Clave del error si ese cambio no vale en este momento, o None."""
    if estado == "no_presentada" and ahora < momento(r):
        return "srv.reservas.antes_de_hora"
    if estado == "confirmada" and r["estado"] in ("sentada", "no_presentada") and ahora >= fin_cortesia(r, a):
        return "srv.reservas.tarde"   # `caducar` la volvería a pasar a no presentada: lo que vale es «sentada»
    return None


def cambiar_estado(r, estado, cuerpo, reservas, a, ahora):
    """Cambio desde la sala (en el sitio). Lanza idiomas.Msg si no vale."""
    if estado not in ESTADOS or estado not in siguientes(r):
        raise idiomas.Msg("srv.reservas.transicion")
    vetado = _vetado(r, estado, a, ahora)
    if vetado == "srv.reservas.antes_de_hora":
        raise idiomas.Msg(vetado, hora=r["hora"])
    if vetado:
        raise idiomas.Msg(vetado)
    if estado == "confirmada" and r["estado"] == "solicitada" and ocupados(reservas, r["fecha"], r["hora"], sin=r["id"]) + r["comensales"] > a["aforo"]:
        raise idiomas.Msg("srv.reservas.lleno")
    if estado in ACTIVAS and r["estado"] not in ACTIVAS:   # vuelve a ocupar aforo (p. ej. deshacer «no presentada»): ¿cabe?
        ya = ocupados(reservas, r["fecha"], r["hora"], sin=r["id"])
        if ya + r["comensales"] > a["aforo"]:
            raise idiomas.Msg("srv.reservas.sin_aforo", hora=r["hora"], ocupados=ya, aforo=a["aforo"], n=r["comensales"])
    if estado in ("rechazada", "cancelada"):
        r["motivo"] = _texto(cuerpo.get("motivo"), "srv.online.motivo", 2, 160)
    if estado == "sentada":
        mesa = cuerpo.get("mesa") or ""
        if not isinstance(mesa, str) or len(mesa.strip()) > 20:
            raise idiomas.Msg("srv.reservas.mesa")
        r["mesa"] = mesa.strip()
    r["estado"] = estado
    r["t"][estado] = ahora.timestamp()


def cancelar_cliente(r, ahora):
    """El cliente cancela con su enlace: solo si está solicitada o confirmada y no ha llegado su hora."""
    if r["estado"] not in ("solicitada", "confirmada") or ahora >= momento(r):
        raise idiomas.Msg("srv.reservas.no_cancelable")
    r["estado"], r["motivo"] = "cancelada", MOTIVO_CLIENTE
    r["t"]["cancelada"] = ahora.timestamp()


# ---------- lo que ven el cliente y la sala ----------
def para_cliente(r, ahora):
    """La página de la reserva del cliente: sin teléfono, correo ni nota."""
    return {"fecha": r["fecha"], "hora": r["hora"], "comensales": r["comensales"], "nombre": r["nombre"], "estado": r["estado"],
            "motivo": r.get("motivo", ""), "cancelable": r["estado"] in ("solicitada", "confirmada") and ahora < momento(r)}


def para_sala(r, a=None, ahora=None):
    """La reserva para la sala, sin el token del cliente y con las acciones que valen ahora mismo (`acciones`)."""
    d = {k: v for k, v in r.items() if k not in ("token",)}
    if a is not None and ahora is not None:
        d["acciones"] = list(siguientes(r, a, ahora))
    return d


def vista_dia(a, reservas, dia, ahora=None):
    """Reservas de un día ordenadas por hora y comensales por tramo frente al aforo."""
    del_dia = sorted((r for r in reservas if r["fecha"] == dia.isoformat()), key=lambda r: (r["hora"], r["creado"]))
    horas = sorted(set(tramos_del_dia(a, dia)) | {r["hora"] for r in del_dia})
    return {"fecha": dia.isoformat(), "aforo": a["aforo"], "reservas": [para_sala(r, a, ahora or datetime.datetime.now()) for r in del_dia],
            "tramos": [{"hora": h, "ocupados": ocupados(reservas, dia.isoformat(), h)} for h in horas]}
