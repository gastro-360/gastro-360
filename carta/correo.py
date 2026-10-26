# SPDX-License-Identifier: EUPL-1.2
"""Envío de correo (Brevo). Biblioteca estándar: la API de Brevo es una petición HTTPS con JSON.

Modos: «real» con BREVO_API_KEY y BREVO_REMITENTE (correo remitente ya validado en Brevo); «prueba» con CORREO_MODO=prueba
(simulador: no sale nada a Internet, lo que enviaría queda en BUZON); sin nada de eso, el canal no está disponible.
La clase real NO está probada contra Brevo (hace falta una cuenta de Brevo)."""
import collections, datetime, json, os, urllib.error, urllib.request

BUZON = collections.deque(maxlen=500)   # lo que ha «enviado» el simulador (se ve en /api/promociones/simulador)
API = "https://api.brevo.com/v3/smtp/email"


def modo():
    if os.environ.get("BREVO_API_KEY") and os.environ.get("BREVO_REMITENTE"):
        return "real"
    return "prueba" if os.environ.get("CORREO_MODO") == "prueba" else None


class Simulado:
    def enviar(self, mensaje):
        BUZON.append({**mensaje, "fecha": datetime.datetime.now().astimezone().isoformat(timespec="seconds")})
        return True, "simulado"


class Brevo:
    def enviar(self, mensaje):
        cuerpo = {"sender": {"name": mensaje["remitente"], "email": os.environ["BREVO_REMITENTE"]},
                  "to": [{"email": mensaje["para"]}], "subject": mensaje["asunto"],
                  "textContent": mensaje["texto"], "htmlContent": mensaje["html"], "headers": mensaje["cabeceras"]}
        req = urllib.request.Request(API, data=json.dumps(cuerpo).encode(), method="POST",
                                     headers={"api-key": os.environ["BREVO_API_KEY"], "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return True, "brevo " + str(json.load(r).get("messageId", ""))[:80]
        except urllib.error.HTTPError as e:
            return False, f"brevo HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:150]}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            return False, f"brevo: {e!r}"[:200]


def enviar(mensaje):
    """mensaje = {para, remitente, asunto, texto, html, cabeceras}. Devuelve (ok, detalle); nunca lanza por un fallo de red."""
    m = modo()
    if m is None:
        return False, "canal de correo no disponible"
    return (Brevo() if m == "real" else Simulado()).enviar(mensaje)
