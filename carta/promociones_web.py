# SPDX-License-Identifier: EUPL-1.2
"""Rutas HTTP de las promociones (solo con sesión del backoffice). servidor.py las llama antes de sus rutas;
cada función devuelve True si ha respondido."""
from urllib.parse import parse_qs, urlparse

import correo, idiomas, promociones, tarjeta_web, wallet_apple, wallet_google

PREFIJO = "/api/promociones"


def _canales():
    return {"email": correo.modo(), "wallet": {"apple": wallet_apple.modo(), "google": wallet_google.modo()}}


def _t(h, clave):
    """Texto de la interfaz en el idioma de la petición (X-Idioma o Accept-Language)."""
    return idiomas.t(clave, idiomas.de_peticion(h.headers))


def _id(h, cuerpo=None):
    v = (cuerpo or {}).get("id") if cuerpo is not None else (parse_qs(urlparse(h.path).query).get("id") or [""])[0]
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def get(h, ruta):
    if ruta not in (PREFIJO, PREFIJO + "/registro", PREFIJO + "/simulador"):
        return False
    if not h.autenticado():
        h.responder(401, {"error": _t(h, "promo.error.sesion")})
    elif ruta == PREFIJO:
        h.responder(200, {"promociones": promociones.listar(), "destinatarios": promociones.destinatarios(), "canales": _canales(),
                          "limite_wallet": promociones.LIMITE_WALLET})
    elif ruta == PREFIJO + "/registro":
        pid = _id(h)
        h.responder(*((200, {"promocion": promociones.obtener(pid), "envios": promociones.registro(pid)}) if pid and promociones.obtener(pid)
                      else (404, {"error": _t(h, "promo.error.no_existe")})))
    elif correo.modo() != "prueba":
        h.responder(404, {"error": _t(h, "promo.error.solo_prueba")})
    else:
        h.responder(200, {"correos": list(correo.BUZON)})
    return True


def post(h, ruta):
    if ruta not in (PREFIJO, PREFIJO + "/enviar"):
        return False
    if not h.autenticado():
        h.responder(401, {"error": _t(h, "promo.error.sesion")})
        return True
    try:
        cuerpo = h.cuerpo_json()
        if not isinstance(cuerpo, dict):
            raise idiomas.Msg("promo.error.no_valida")
    except Exception:   # noqa: BLE001
        h.responder(400, {"error": _t(h, "promo.error.no_valida")})
        return True
    if ruta == PREFIJO:
        try:
            pid = promociones.crear(cuerpo.get("titulo"), cuerpo.get("texto"), cuerpo.get("canales"))
        except ValueError as e:
            h.responder(400, {"error": idiomas.mensaje(e, idiomas.de_peticion(h.headers))})
            return True
        h.responder(200, {"id": pid})
        return True
    pid = _id(h, cuerpo)
    if not pid or not promociones.obtener(pid):
        h.responder(404, {"error": _t(h, "promo.error.no_existe")})
    elif not promociones.ejecutar(pid, tarjeta_web.base_url(h), segundo_plano=True):
        h.responder(409, {"error": _t(h, "promo.error.ya_enviada")})
    else:
        h.responder(202, {"ok": True, "id": pid})
    return True


def delete(h, ruta):
    if ruta != PREFIJO:
        return False
    if not h.autenticado():
        h.responder(401, {"error": _t(h, "promo.error.sesion")})
    elif not promociones.borrar_borrador(_id(h) or 0):
        h.responder(404, {"error": _t(h, "promo.error.solo_borradores")})
    else:
        h.responder(200, {"ok": True})
    return True
