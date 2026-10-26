# SPDX-License-Identifier: EUPL-1.2
"""Apple Wallet: la tarjeta de sellos como .pkpass firmado, y el aviso (push) para que el móvil la actualice.

El .pkpass es un zip con pass.json, imágenes, manifest.json (SHA-1 de cada archivo) y `signature`: firma PKCS#7 separada
del manifiesto, hecha con el certificado del Pass Type ID y la cadena de Apple (WWDR). Se firma con `openssl smime`
(sin dependencias nuevas). Con WALLET_MODO=prueba y sin credenciales reales se usa una CA y un certificado de PRUEBA
autogenerados: sirven para comprobar que el paquete se genera y la firma verifica, pero un iPhone NO los acepta."""
import hashlib, io, json, os, subprocess, tempfile, zipfile

import idiomas, restaurante, sellos, wallet

REAL = ("pass.pem", "pass.key", "wwdr.pem")   # certificado + clave del Pass Type ID, y el intermedio WWDR de Apple


def _carpeta_real():
    return os.path.join(wallet.WALLET_DIR, "apple")


def modo():
    """«real» con las credenciales puestas, «prueba» con WALLET_MODO=prueba, None si el canal no está disponible."""
    if all(os.path.isfile(os.path.join(_carpeta_real(), f)) for f in REAL) and identificadores(real=True):
        return "real"
    return "prueba" if wallet.modo_prueba() else None


def identificadores(real=None):
    """(pass_type_id, team_id) de sellos.json → wallet.apple; en modo prueba, unos de mentira."""
    a = (sellos.config().get("wallet") or {}).get("apple") or {}
    if a.get("pass_type_id") and a.get("team_id"):
        return a["pass_type_id"], a["team_id"]
    return None if real else (f"pass.prueba.{restaurante.NOMBRE}.sellos", "PRUEBA0000")


def _generar_prueba(carpeta):
    wallet.openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{carpeta}/wwdr.key", "-out", f"{carpeta}/wwdr.pem",
                   "-days", "3650", "-subj", "/CN=PRUEBA Apple WWDR CA/O=PRUEBA (no es de Apple)")
    wallet.openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{carpeta}/pass.key", "-out", f"{carpeta}/pass.csr",
                   "-subj", "/CN=PRUEBA Pass Type ID/O=PRUEBA (no es de Apple)")
    wallet.openssl("x509", "-req", "-in", f"{carpeta}/pass.csr", "-CA", f"{carpeta}/wwdr.pem", "-CAkey", f"{carpeta}/wwdr.key",
                   "-CAcreateserial", "-out", f"{carpeta}/pass.pem", "-days", "3650")


def credenciales():
    """Carpeta con pass.pem, pass.key y wwdr.pem: la real o, en modo prueba, la de certificados de prueba."""
    m = modo()
    if m == "real":
        return _carpeta_real()
    if m == "prueba":
        return wallet.preparar_prueba("apple", _generar_prueba)
    raise RuntimeError("Apple Wallet no está disponible: faltan credenciales y WALLET_MODO=prueba")


def ca_publica():
    """Certificado (público) con el que se comprueba la firma: el WWDR."""
    with open(os.path.join(credenciales(), "wwdr.pem"), encoding="utf-8") as f:
        return f.read()


# ---------- imágenes ----------
def _png_liso(ancho, alto, rgb):
    import struct, zlib
    fila = b"\x00" + bytes(rgb) * ancho
    def trozo(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(fila * alto)) + trozo(b"IEND", b""))


def _imagenes(marca):
    """icon, logo (y @2x). Con Pillow se parte del logo del restaurante; sin él, cuadrados del color de marca."""
    hexa = marca["colores"]["acento"].lstrip("#")
    rgb = tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))
    try:
        from PIL import Image
        img = Image.open(os.path.join(restaurante.MARCA_DIR, marca["logo"])).convert("RGBA")
        def png(w, h):
            c = img.copy()
            c.thumbnail((w, h))
            lienzo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            lienzo.paste(c, ((w - c.width) // 2, (h - c.height) // 2))
            b = io.BytesIO()
            lienzo.save(b, "PNG")
            return b.getvalue()
    except Exception:   # noqa: BLE001  (sin Pillow o logo ilegible)
        png = lambda w, h: _png_liso(w, h, rgb)
    return {"icon.png": png(29, 29), "icon@2x.png": png(58, 58), "logo.png": png(160, 50), "logo@2x.png": png(320, 100)}


# ---------- el pase ----------
def _rgb(h):
    h = h.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(h[i:i + 2], 16) for i in (0, 2, 4)))


def pass_json(e, auth, base_url, marca, idioma=idiomas.FUENTE):
    """pass.json de una tarjeta; `e` es sellos.estado(). Los textos fijos salen en `idioma` (los del local y los de la promoción, tal cual)."""
    tipo, equipo = identificadores()
    t = lambda clave, **p: idiomas.t(clave, idioma, **p)
    c = marca["colores"]
    falta = max(0, e["sellos_meta"] - e["sellos"])
    p = {
        "formatVersion": 1, "passTypeIdentifier": tipo, "teamIdentifier": equipo, "serialNumber": e["id"],
        "organizationName": marca["nombre"], "description": t("wallet.apple.descripcion", nombre=marca["nombre"]),
        "logoText": marca["nombre_corto"],
        "backgroundColor": _rgb(c["fondo"]), "foregroundColor": "rgb(255, 255, 255)", "labelColor": _rgb(c["acento"]),
        "authenticationToken": auth, "webServiceURL": base_url.rstrip("/") + "/wallet/apple",
        "barcodes": [{"format": "PKBarcodeFormatQR", "message": e["id"], "messageEncoding": "iso-8859-1"}],
        "barcode": {"format": "PKBarcodeFormatQR", "message": e["id"], "messageEncoding": "iso-8859-1"},
        "storeCard": {
            "headerFields": [{"key": "sellos", "label": t("wallet.apple.etiqueta_sellos"), "value": f"{e['sellos']} / {e['sellos_meta']}",
                              "changeMessage": t("wallet.apple.cambio_sellos")}],
            "primaryFields": [{"key": "premio", "label": t("wallet.apple.etiqueta_premio"), "value": e["premio"]}],
            "secondaryFields": [{"key": "estado", "label": t("wallet.apple.etiqueta_estado"),
                                 "value": t("wallet.apple.premio_listo") if e["premios_disponibles"] else t("wallet.apple.faltan", falta=falta)}],
            "backFields": [{"key": "como", "label": t("wallet.apple.como_etiqueta"),
                            "value": t("wallet.apple.como_texto", importe=idiomas.moneda(sellos.config()["importe_minimo"], idioma),
                                       meta=e["sellos_meta"], premio=e["premio"])}],
        },
    }
    if e.get("aviso"):
        # Promoción vigente: al cambiar su valor, el móvil enseña el changeMessage como aviso. Lleva siempre el enlace de baja.
        a = e["aviso"]
        p["storeCard"]["backFields"] += [
            {"key": "aviso", "label": a["titulo"], "value": a["texto"], "changeMessage": a["titulo"] + ": %@"},
            {"key": "baja", "label": t("wallet.promociones"), "value": t("wallet.baja"),
             "attributedValue": f'<a href="{a["baja_url"]}">{t("wallet.baja")}</a>'}]
    url = restaurante.resena_url(marca)
    if url:
        # El mismo enlace para todos, sin condiciones ni nada a cambio (política de Google)
        p["storeCard"]["backFields"].append({"key": "resena", "label": t("wallet.resena_etiqueta"), "value": t("wallet.resena"), "attributedValue": f'<a href="{url}">{t("wallet.resena")}</a>'})
    return p


def firmar(manifiesto):
    """Firma separada (PKCS#7, DER) del manifiesto con el certificado del Pass Type ID y la cadena WWDR."""
    c = credenciales()
    return wallet.openssl("smime", "-sign", "-binary", "-outform", "DER", "-signer", f"{c}/pass.pem", "-inkey", f"{c}/pass.key",
                          "-certfile", f"{c}/wwdr.pem", entrada=manifiesto)


def construir(tid, base_url, idioma=None):
    """Bytes del .pkpass actual de la tarjeta (con sus sellos de ahora). None si la tarjeta no existe.
    `idioma`: por defecto el de la tarjeta (el del cliente vinculado o el de quien la pidió)."""
    e = sellos.estado(tid)
    if not e:
        return None
    idioma = idiomas.valido(idioma) or idiomas.valido(e.get("idioma")) or idiomas.FUENTE
    marca = restaurante.marca()
    archivos = {"pass.json": json.dumps(pass_json(e, sellos.auth_token(tid), base_url, marca, idioma), ensure_ascii=False).encode("utf-8"),
                **_imagenes(marca)}
    manifiesto = json.dumps({n: hashlib.sha1(d).hexdigest() for n, d in archivos.items()}).encode()
    archivos.update({"manifest.json": manifiesto, "signature": firmar(manifiesto)})
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in archivos.items():
            z.writestr(n, d)
    return salida.getvalue()


def verificar(datos, ca_pem):
    """Comprueba un .pkpass: los SHA-1 del manifiesto coinciden con los archivos y la firma verifica contra `ca_pem`.
    Devuelve (True, "") o (False, motivo)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
        manifiesto, firma = z.read("manifest.json"), z.read("signature")
        hashes = json.loads(manifiesto)
        for n in z.namelist():
            if n not in ("manifest.json", "signature") and hashes.get(n) != hashlib.sha1(z.read(n)).hexdigest():
                return False, f"el hash de {n} no coincide con el manifiesto"
        if sorted(hashes) != sorted(n for n in z.namelist() if n not in ("manifest.json", "signature")):
            return False, "el manifiesto no lista exactamente los archivos del pase"
    except Exception as e:   # noqa: BLE001
        return False, f"no es un .pkpass válido: {e}"
    with tempfile.TemporaryDirectory() as d:
        for nombre, contenido in (("manifest.json", manifiesto), ("signature", firma), ("ca.pem", ca_pem.encode())):
            with open(os.path.join(d, nombre), "wb") as f:
                f.write(contenido)
        r = subprocess.run(["openssl", "smime", "-verify", "-binary", "-inform", "DER", "-in", f"{d}/signature", "-content", f"{d}/manifest.json",
                            "-CAfile", f"{d}/ca.pem", "-purpose", "any", "-out", os.devnull], capture_output=True)
    return (True, "") if r.returncode == 0 else (False, r.stderr.decode("utf-8", "replace").strip()[:300])


# ---------- aviso (push) a los móviles con la tarjeta ----------
class ApnsSimulado:
    """Anota el push que enviaría a Apple (api.push.apple.com): sin red."""
    def enviar(self, push_token, topic):
        wallet.anotar("apns", push_token=push_token, topic=topic)
        return True


class ApnsReal:
    """Push vacío al APNs de Apple con el certificado del Pass Type ID (necesita HTTP/2: se hace con curl).
    SIN PROBAR contra Apple: hace falta la cuenta Apple Developer del restaurante."""
    def enviar(self, push_token, topic):
        c = _carpeta_real()
        r = subprocess.run(["curl", "--silent", "--show-error", "--http2", "--cert", f"{c}/pass.pem", "--key", f"{c}/pass.key",
                            "--header", f"apns-topic: {topic}", "--data", "{}", "--write-out", "%{http_code}", "--output", os.devnull,
                            f"https://api.push.apple.com/3/device/{push_token}"], capture_output=True, timeout=20)
        return r.stdout.decode().strip() == "200"


def cliente_apns():
    return ApnsReal() if modo() == "real" else ApnsSimulado()


def empujar(tid):
    """Avisa a cada móvil que tiene esta tarjeta: al recibirlo pregunta qué ha cambiado y descarga la tarjeta nueva."""
    if modo() is None:
        return 0
    tipo, _ = identificadores()
    apns = cliente_apns()
    return sum(1 for token in sellos.push_tokens(tid) if apns.enviar(token, tipo))
