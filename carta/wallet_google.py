# SPDX-License-Identifier: EUPL-1.2
"""Google Wallet: la tarjeta de sellos como clase y objeto de fidelización (loyalty), enlace «Añadir a Google Wallet» y
actualización del objeto tras cada sello.

El enlace de guardado es un JWT firmado con la clave de la cuenta de servicio (RS256, con `openssl dgst`: sin dependencias nuevas)
que lleva la clase y el objeto dentro. Para actualizar el objeto después hay que hablar con la API REST de Google: eso lo hace un
cliente (GoogleReal) o, sin credenciales y con WALLET_MODO=prueba, un simulador que anota las llamadas (GoogleSimulado).
La clave de prueba verifica la firma del JWT, pero Google no la acepta."""
import base64, json, os, subprocess, tempfile, time, urllib.error, urllib.parse, urllib.request

import idiomas, restaurante, sellos, wallet

API = "https://walletobjects.googleapis.com/walletobjects/v1"
ALCANCE = "https://www.googleapis.com/auth/wallet_object.issuer"


def _archivo_real():
    return os.path.join(wallet.WALLET_DIR, "google", "service_account.json")


def issuer_id():
    g = (sellos.config().get("wallet") or {}).get("google") or {}
    return g.get("issuer_id") or None


def modo():
    """«real» con la cuenta de servicio y el issuer_id puestos, «prueba» con WALLET_MODO=prueba, None si no hay canal."""
    if os.path.isfile(_archivo_real()) and issuer_id():
        return "real"
    return "prueba" if wallet.modo_prueba() else None


def _generar_prueba(carpeta):
    wallet.openssl("genrsa", "-out", f"{carpeta}/clave.pem", "2048")
    with open(f"{carpeta}/clave.pem", encoding="utf-8") as k, open(f"{carpeta}/service_account.json", "w", encoding="utf-8") as f:
        json.dump({"client_email": "prueba@prueba.iam.gserviceaccount.com", "private_key": k.read(),
                   "token_uri": "https://oauth2.googleapis.com/token"}, f)


def cuenta():
    """Cuenta de servicio (client_email, private_key): la real o, en modo prueba, una de prueba autogenerada."""
    m = modo()
    if m is None:
        raise RuntimeError("Google Wallet no está disponible: faltan credenciales y WALLET_MODO=prueba")   # para el operador
    ruta = _archivo_real() if m == "real" else os.path.join(wallet.preparar_prueba("google", _generar_prueba), "service_account.json")
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def clave_publica():
    """Clave pública (PEM) con la que se comprueba la firma del enlace."""
    return wallet.openssl("pkey", "-pubout", entrada=cuenta()["private_key"].encode()).decode()


def ids(tid):
    emisor = issuer_id() or "3388000000000000000"   # en modo prueba, un emisor de mentira
    return f"{emisor}.{restaurante.NOMBRE.replace('_', '-')}-sellos", f"{emisor}.{tid}"


# ---------- clase y objeto ----------
def clase(marca, base_url, idioma=idiomas.FUENTE):
    """Clase única del local (la comparten todas las tarjetas): sus textos salen en el idioma de la primera tarjeta que se guarda."""
    clase_id, _ = ids("")
    c = sellos.config()
    return {"id": clase_id, "issuerName": marca["nombre"], "programName": idiomas.t("wallet.google.programa", idioma, nombre=marca["nombre_corto"]),
            "programLogo": {"sourceUri": {"uri": base_url.rstrip("/") + "/img/" + marca["logo"]}, "contentDescription": {"defaultValue": {"language": idioma, "value": marca["nombre"]}}},
            "hexBackgroundColor": marca["colores"]["fondo"], "countryCode": "ES", "reviewStatus": "UNDER_REVIEW",
            "rewardsTierLabel": idiomas.t("wallet.google.premio", idioma), "rewardsTier": sellos.premio_en(c, idioma)}


def parche(e, idioma=idiomas.FUENTE):
    """Lo que cambia con cada sello: el saldo y el estado. Es lo que se manda al actualizar el objeto."""
    t = lambda clave, **p: idiomas.t(clave, idioma, **p)
    textos = [{"id": "premio", "header": t("wallet.google.premio"), "body": e["premio"]}]
    if e.get("aviso"):
        textos.append({"id": "aviso", "header": e["aviso"]["titulo"], "body": e["aviso"]["texto"]})
    return {"loyaltyPoints": {"label": t("wallet.google.sellos"), "balance": {"string": f"{e['sellos']} / {e['sellos_meta']}"}},
            "secondaryLoyaltyPoints": {"label": t("wallet.google.estado"), "balance": {"string": t("wallet.google.premio_listo") if e["premios_disponibles"]
                                                                                          else t("wallet.google.faltan", falta=max(0, e["sellos_meta"] - e["sellos"]))}},
            "textModulesData": textos}


def objeto(e, marca, idioma=idiomas.FUENTE):
    clase_id, obj_id = ids(e["id"])
    o = {"id": obj_id, "classId": clase_id, "state": "ACTIVE", "accountId": e["id"], "accountName": idiomas.t("wallet.google.cuenta", idioma),
         "barcode": {"type": "QR_CODE", "value": e["id"], "alternateText": e["id"]}, **parche(e, idioma)}
    url = restaurante.resena_url(marca)
    uris = [{"id": "resena", "uri": url, "description": idiomas.t("wallet.resena", idioma)}] if url else []   # el mismo enlace para todos, sin condiciones (política de Google)
    if e.get("aviso"):
        uris.append({"id": "baja", "uri": e["aviso"]["baja_url"], "description": idiomas.t("wallet.baja", idioma)})
    if uris:
        o["linksModuleData"] = {"uris": uris}
    return o


# ---------- enlace «Añadir a Google Wallet» ----------
def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def firmar_jwt(claims, clave_pem):
    cabecera = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    cuerpo = _b64(json.dumps(claims, ensure_ascii=False, separators=(",", ":")).encode())
    return f"{cabecera}.{cuerpo}.{_b64(_firmar_rs256(f'{cabecera}.{cuerpo}'.encode(), clave_pem))}"


def _firmar_rs256(datos, clave_pem):
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "clave.pem")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(clave_pem)
        os.chmod(ruta, 0o600)
        return wallet.openssl("dgst", "-sha256", "-sign", ruta, entrada=datos)


def verificar_jwt(jwt, clave_publica_pem):
    """True si la firma RS256 del JWT verifica con la clave pública (PEM)."""
    try:
        cab, cuerpo, firma = jwt.split(".")
        firma_bin = base64.urlsafe_b64decode(firma + "=" * (-len(firma) % 4))
    except ValueError:
        return False
    with tempfile.TemporaryDirectory() as d:
        for n, c in (("pub.pem", clave_publica_pem.encode()), ("firma", firma_bin)):
            with open(os.path.join(d, n), "wb") as f:
                f.write(c)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", f"{d}/pub.pem", "-signature", f"{d}/firma"],
                           input=f"{cab}.{cuerpo}".encode(), capture_output=True)
    return r.returncode == 0


def _idioma(e, idioma):
    """El pedido a mano, si lo hay; si no, el de la tarjeta."""
    return idiomas.valido(idioma) or idiomas.valido(e.get("idioma")) or idiomas.FUENTE


def enlace_guardar(tid, base_url, idioma=None):
    """https://pay.google.com/gp/v/save/<jwt> con la clase y el objeto de la tarjeta. None si no existe.
    `idioma`: por defecto el de la tarjeta."""
    e = sellos.estado(tid)
    if not e:
        return None
    idioma = _idioma(e, idioma)
    marca, cta = restaurante.marca(), cuenta()
    claims = {"iss": cta["client_email"], "aud": "google", "typ": "savetowallet", "iat": int(time.time()),
              "origins": [base_url.rstrip("/")],
              "payload": {"loyaltyClasses": [clase(marca, base_url, idioma)], "loyaltyObjects": [objeto(e, marca, idioma)]}}
    return "https://pay.google.com/gp/v/save/" + firmar_jwt(claims, cta["private_key"])


# ---------- clientes de la API REST ----------
class GoogleSimulado:
    """Anota las llamadas que haría a la API de Google Wallet: sin red."""
    def parchear_objeto(self, obj_id, cuerpo):
        wallet.anotar("google", operacion="parchear_objeto", objeto=obj_id, cuerpo=cuerpo)
        return True

    def anadir_mensaje(self, obj_id, mensaje):
        wallet.anotar("google", operacion="anadir_mensaje", objeto=obj_id, mensaje=mensaje)
        return True


class GoogleReal:
    """API REST de Google Wallet con OAuth de cuenta de servicio (JWT bearer). SIN PROBAR contra Google: hace falta la
    cuenta emisora y la cuenta de servicio del restaurante."""
    def _token(self):
        cta = cuenta()
        ahora = int(time.time())
        jwt = firmar_jwt({"iss": cta["client_email"], "scope": ALCANCE, "aud": cta.get("token_uri", "https://oauth2.googleapis.com/token"),
                          "iat": ahora, "exp": ahora + 3600}, cta["private_key"])
        datos = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}).encode()
        with urllib.request.urlopen(urllib.request.Request(cta.get("token_uri", "https://oauth2.googleapis.com/token"), data=datos), timeout=15) as r:
            return json.load(r)["access_token"]

    def _llamar(self, ruta, cuerpo, metodo):
        req = urllib.request.Request(f"{API}/{ruta}", data=json.dumps(cuerpo).encode(), method=metodo,
                                     headers={"Authorization": "Bearer " + self._token(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:   # la tarjeta aún no se ha guardado en ningún móvil: no hay nada que actualizar
                return False
            raise

    def parchear_objeto(self, obj_id, cuerpo):
        return self._llamar(f"loyaltyObject/{urllib.parse.quote(obj_id, safe='')}", cuerpo, "PATCH")

    def anadir_mensaje(self, obj_id, mensaje):
        """Mensaje del objeto; con messageType TEXT_AND_NOTIFY Google lo avisa al móvil (tiene su propio límite diario)."""
        return self._llamar(f"loyaltyObject/{urllib.parse.quote(obj_id, safe='')}/addMessage", {"message": mensaje}, "POST")


def cliente():
    return GoogleReal() if modo() == "real" else GoogleSimulado()


def actualizar(tid, idioma=None):
    """Actualiza el objeto de Google de la tarjeta con sus sellos de ahora (en `idioma`; por defecto el de la tarjeta)."""
    if modo() is None:
        return
    e = sellos.estado(tid)
    if e:
        cliente().parchear_objeto(ids(tid)[1], parche(e, _idioma(e, idioma)))


def avisar(tid, titulo, texto, idioma=None):
    """Promoción: actualiza el objeto (para que la lleve) y añade un mensaje con aviso. True si Google tiene la tarjeta.
    `idioma`: el de los textos fijos (por defecto el de la tarjeta)."""
    if modo() is None:
        return False
    e = sellos.estado(tid)
    if not e:
        return False
    idioma = _idioma(e, idioma)
    c = cliente()
    c.parchear_objeto(ids(tid)[1], parche(e, idioma))
    return bool(c.anadir_mensaje(ids(tid)[1], {"header": titulo, "body": texto + "\n" + idiomas.t("wallet.google.mensaje_baja", idioma, enlace=e["aviso"]["baja_url"]),
                                               "messageType": "TEXT_AND_NOTIFY"}))
