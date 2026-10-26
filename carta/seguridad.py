# SPDX-License-Identifier: EUPL-1.2
"""Cabeceras de seguridad de las páginas HTML: Content-Security-Policy restrictiva sin 'unsafe-inline' ni 'unsafe-eval' en scripts.
Los <script> en línea se autorizan por su huella sha256, calculada sobre el HTML que se va a enviar (valen también las páginas
estáticas). Los estilos en línea sí se permiten: son atributos style="" generados por la interfaz y, con img/connect/font solo
'self', un estilo inyectado no puede sacar datos ni ejecutar código."""
import base64, hashlib, re

_SCRIPT_EN_LINEA = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def huellas_scripts(html):
    return ["'sha256-" + base64.b64encode(hashlib.sha256(m.encode("utf-8")).digest()).decode() + "'" for m in _SCRIPT_EN_LINEA.findall(html)]


def csp(html=""):
    scripts = " ".join(["'self'"] + huellas_scripts(html))
    return ("default-src 'self'; script-src " + scripts + "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")


CABECERAS_FIJAS = (("Referrer-Policy", "no-referrer"), ("X-Content-Type-Options", "nosniff"))
