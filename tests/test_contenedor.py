# SPDX-License-Identifier: EUPL-1.2
"""Batería HTTP contra el contenedor ya levantado (a través de Caddy, por HTTPS).
No arranca nada: la lanza tests/contenedor.sh.   CARTA_URL (https://localhost:8443)  CARTA_CLAVE (contraseña del backoffice)"""
import http.cookiejar, json, os, ssl, unittest, urllib.error, urllib.request

URL = os.environ.get("CARTA_URL", "https://localhost:8443").rstrip("/")
CLAVE = os.environ.get("CARTA_CLAVE", "")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE   # Caddy usa su CA interna con DOMINIO=localhost


def setUpModule():
    if "CARTA_URL" not in os.environ:
        raise unittest.SkipTest("va contra el contenedor levantado: lánzala con tests/contenedor.sh")


class Cliente:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies), urllib.request.HTTPSHandler(context=CTX))

    def pedir(self, metodo, ruta, cuerpo=None, cabeceras=None):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode()
        req = urllib.request.Request(URL + ruta, data=datos, method=metodo, headers={"Content-Type": "application/json", **(cabeceras or {})})
        try:
            with self.op.open(req, timeout=15) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def json(self, metodo, ruta, cuerpo=None):
        c, b, _ = self.pedir(metodo, ruta, cuerpo)
        return c, json.loads(b or b"{}")

    def entrar(self):
        c, _ = self.json("POST", "/api/login", {"clave": CLAVE})
        assert c == 200, "login falló: ¿CARTA_CLAVE correcta?"


def un_producto():
    c, b, _ = Cliente().pedir("GET", "/datos.js")
    d = json.loads(b.decode().split("window.DATOS = ", 1)[1].split(";\nwindow.", 1)[0])
    return d, next(x for x in d["platos"] if not x.get("oculto"))["id"]


class Contenedor(unittest.TestCase):
    def tearDown(self):
        a = Cliente()
        a.entrar()
        a.json("POST", "/api/aceptar", {"aceptar_pedidos": True})

    def test_salud(self):
        c, j = Cliente().json("GET", "/salud")
        self.assertEqual(c, 200)
        self.assertTrue(j["ok"])
        self.assertEqual(j["problemas"], [])

    def test_paginas(self):
        cl = Cliente()
        for ruta in ("/", "/admin", "/cocina", "/datos.js", "/manifest.webmanifest"):
            c, b, _ = cl.pedir("GET", ruta)
            self.assertEqual(c, 200, ruta)
            self.assertTrue(b, ruta)
        self.assertNotIn(b"{{", cl.pedir("GET", "/")[1])
        self.assertNotIn(b"{{", cl.pedir("GET", "/cocina")[1])

    def test_http_redirige_a_https(self):
        import http.client
        host, puerto = URL.split("//")[1].rsplit(":", 1)
        puerto_http = os.environ.get("CARTA_HTTP_PORT")
        if not puerto_http:
            self.skipTest("sin CARTA_HTTP_PORT")
        con = http.client.HTTPConnection(host, int(puerto_http), timeout=10)
        con.request("GET", "/")
        r = con.getresponse()
        self.assertIn(r.status, (301, 302, 307, 308))
        self.assertTrue(r.getheader("Location").startswith("https://"))

    def test_api_protegida(self):
        cl = Cliente()
        self.assertEqual(cl.pedir("GET", "/api/pedidos")[0], 401)
        self.assertEqual(cl.pedir("POST", "/api/aceptar", {"aceptar_pedidos": False})[0], 401)

    def test_interruptor_aceptar_pedidos(self):
        d, pid = un_producto()
        mesa = (d.get("mesas") or [{"n": 1}])[0]["n"]
        pedido = {"mesa": mesa, "lineas": [{"pid": pid, "rm": [], "ex": []}]}
        cl, admin = Cliente(), Cliente()
        admin.entrar()
        self.assertEqual(cl.json("GET", "/api/estado")[1]["aceptar_pedidos"], True)
        # cerrado: la carta no deja enviar y lo dice
        self.assertEqual(admin.json("POST", "/api/aceptar", {"aceptar_pedidos": False})[0], 200)
        c, j = cl.json("GET", "/api/estado")
        self.assertFalse(j["aceptar_pedidos"])
        self.assertTrue(j["mensaje"])
        c, j = cl.json("POST", "/api/pedido", pedido)
        self.assertEqual(c, 503)
        self.assertIn("no se aceptan pedidos", j["error"])
        self.assertFalse(admin.json("GET", "/api/pedidos")[1]["aceptar_pedidos"])
        # abierto otra vez: entra y llega a cocina
        admin.json("POST", "/api/aceptar", {"aceptar_pedidos": True})
        c, p = cl.json("POST", "/api/pedido", pedido)
        self.assertEqual(c, 200, p)
        ids = [x["id"] for x in admin.json("GET", "/api/pedidos")[1]["pedidos"]]
        self.assertIn(p["id"], ids)
        self.assertEqual(admin.json("POST", "/api/pedido/estado", {"id": p["id"], "estado": "entregado"})[0], 200)


# Por defecto el alta es directa; con CONFIRMACION_DOBLE=1 (exportada al lanzar contenedor.sh) se prueba la doble confirmación
DOBLE = os.environ.get("CONFIRMACION_DOBLE", "").strip().lower() in ("1", "true", "si", "sí", "yes")


def token_confirmacion(admin, email, intentos=100):
    """Token del correo de confirmación que el simulador (CORREO_MODO=prueba) guardó para `email` (no es publicidad)."""
    import re, time
    for _ in range(intentos):
        for m in admin.json("GET", "/api/promociones/simulador")[1]["correos"]:
            if m["para"] == email.lower() and not m["asunto"].startswith("Publicidad:"):
                t = re.search(r"/confirmar\?t=([\w\-]+)", m["texto"])
                if t:
                    return t.group(1)
        time.sleep(0.1)
    return None


class Permiso(unittest.TestCase):
    """alta con permiso -> ficha con prueba -> baja confirmada -> ya no es apto para marketing."""

    def setUp(self):
        self.d, self.pid = un_producto()
        self.mesa = (self.d.get("mesas") or [{"n": 1}])[0]["n"]
        self.admin = Cliente()
        self.admin.entrar()

    def pedido(self, cl, permiso=None):
        cuerpo = {"mesa": self.mesa, "lineas": [{"pid": self.pid, "rm": [], "ex": []}]}
        if permiso is not None:
            cuerpo["permiso"] = permiso
        return cl.json("POST", "/api/pedido", cuerpo)

    def ficha(self, email):
        c, j = self.admin.json("GET", "/api/clientes")
        self.assertEqual(c, 200)
        return next((x for x in j["clientes"] if x["email"] == email), None)

    def test_alta_ficha_baja(self):
        import re, time
        email = f"prueba{int(time.time() * 1000)}@example.com"
        cl = Cliente()
        c, t = cl.json("GET", "/api/permiso")
        self.assertEqual(c, 200)
        self.assertTrue(t["texto"] and t["version"])
        # sin permiso: el email no se guarda
        self.assertEqual(self.pedido(cl)[0], 200)
        self.assertIsNone(self.ficha(email))
        # versión de texto equivocada: se rechaza y no se guarda
        self.assertEqual(self.pedido(cl, {"email": email, "version": "0"})[0], 400)
        self.assertIsNone(self.ficha(email))
        # email malo: se rechaza
        self.assertEqual(self.pedido(cl, {"email": "no-es-un-correo", "version": t["version"]})[0], 400)
        # alta con permiso
        c, p = self.pedido(cl, {"email": email.upper(), "version": t["version"]})
        self.assertEqual(c, 200, p)
        self.assertNotIn("cliente", p)   # lo que ve el cliente no lleva datos de la ficha
        if DOBLE:
            self.assertEqual(p.get("permiso"), "confirmar")
            # doble confirmación: hasta confirmar por correo está pendiente y NO es apto
            f = self.ficha(email)
            self.assertFalse(f["apto_marketing"])
            self.assertTrue(f["pendiente"])
            self.assertEqual(f["permisos"], [])
            tok = token_confirmacion(self.admin, email)
            self.assertTrue(tok, "el correo de confirmación llega")
            self.assertEqual(cl.json("POST", "/api/confirmar", {"token": "x" * 32})[0], 404)
            self.assertEqual(cl.json("POST", "/api/confirmar", {"token": tok})[0], 200)
            self.assertEqual(cl.json("POST", "/api/confirmar", {"token": tok})[0], 404, "el token vale una vez")
            canal = "pedido-carta+enlace-confirmacion"
        else:
            # alta directa: marcar la casilla basta, sin solicitud ni correo de confirmación
            self.assertEqual(p.get("permiso"), "alta")
            self.assertIsNone(token_confirmacion(self.admin, email, intentos=5), "en alta directa no se manda correo de confirmación")
            canal = "pedido-carta"
        f = self.ficha(email)
        self.assertTrue(f["apto_marketing"])
        self.assertIsNone(f["pendiente"])
        self.assertEqual(len(f["permisos"]), 1)
        prueba = f["permisos"][0]
        self.assertEqual(prueba["accion"], "alta")
        self.assertEqual(prueba["texto"], t["texto"])
        self.assertEqual(prueba["texto_version"], t["version"])
        self.assertEqual(prueba["canal"], canal)
        self.assertRegex(prueba["fecha"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        # la ficha pide sesión
        self.assertEqual(Cliente().pedir("GET", "/api/clientes")[0], 401)
        # baja: enlace -> página con confirmación -> POST
        token = self.admin_token(email)
        c, cuerpo, _ = cl.pedir("GET", "/baja?t=" + token)
        self.assertEqual(c, 200)
        self.assertIn("Sí, darme de baja", cuerpo.decode())
        self.assertTrue(self.ficha(email)["apto_marketing"], "abrir el enlace no da de baja: falta la confirmación")
        self.assertEqual(cl.json("POST", "/api/baja", {"token": "x" * 32})[0], 404)
        self.assertEqual(cl.json("POST", "/api/baja", {"token": token})[0], 200)
        f = self.ficha(email)
        self.assertFalse(f["apto_marketing"])
        self.assertEqual([x["accion"] for x in f["permisos"]], ["alta", "baja"])
        self.assertRegex(f["permisos"][1]["fecha"], r"^\d{4}-\d\d-\d\dT")
        # repetir la baja no ensucia el registro
        self.assertEqual(cl.json("POST", "/api/baja", {"token": token})[0], 200)
        self.assertEqual(len(self.ficha(email)["permisos"]), 2)
        # token inválido: la página lo dice y no ofrece botón
        c, cuerpo, _ = cl.pedir("GET", "/baja?t=nope")
        self.assertIn("no es válido", cuerpo.decode())

    def admin_token(self, email):
        # El token solo lo ve quien lo recibe; aquí se lee de la base de datos dentro del contenedor.
        import subprocess
        r = subprocess.run(["docker", "compose", "-p", "cartatest", "exec", "-T", "app", "python", "-c",
                            "import sys; sys.path.insert(0,'/app/carta'); import clientes, sqlite3; "
                            f"print(sqlite3.connect(clientes.DB).execute('select token_baja from clientes where email=?', ('{email.lower()}',)).fetchone()[0])"],
                           capture_output=True, text=True, check=True)
        return r.stdout.strip()


def escribir(ruta, datos):
    with open(ruta, "wb" if isinstance(datos, bytes) else "w") as f:
        f.write(datos)


class Sellos(unittest.TestCase):
    """tarjeta de sellos. Servido -> sello (uno por pedido), canje, .pkpass firmado, servicio web de Apple y Google (simulados)."""

    tokens = {}   # id de pedido -> token que recibió quien lo hizo

    @classmethod
    def setUpClass(cls):
        cls.admin = Cliente()
        cls.admin.entrar()
        cls.d, cls.pid = un_producto()
        cls.mesa = (cls.d.get("mesas") or [{"n": 1}])[0]["n"]
        c, cls.antes = cls.admin.json("GET", "/api/sellos/config")
        assert c == 200
        cls.ajustes(cls, meta=2, minimo=0)

    @classmethod
    def tearDownClass(cls):
        cls.ajustes(cls, meta=cls.antes["sellos_meta"], minimo=cls.antes["importe_minimo"], activo=cls.antes["activo"], premio=cls.antes["premio"])

    def ajustes(self, meta, minimo, activo=True, premio="Café de prueba"):
        c, j = self.admin.json("PUT", "/api/sellos/config", {"activo": activo, "sellos_meta": meta, "premio": premio, "importe_minimo": minimo})
        assert c == 200, j

    def nueva(self):
        c, t = Cliente().json("POST", "/api/tarjeta")
        self.assertEqual(c, 200, t)
        return t["id"]

    def pedido(self, tarjeta=None):
        cuerpo = {"mesa": self.mesa, "lineas": [{"pid": self.pid, "rm": [], "ex": []}]}
        if tarjeta:
            cuerpo["tarjeta"] = tarjeta
        c, p = Cliente().json("POST", "/api/pedido", cuerpo)
        self.assertEqual(c, 200, p)
        self.assertNotIn("tarjeta", p)   # el pedido que ve el cliente no lleva el vínculo
        self.tokens[p["id"]] = p["token"]   # lo que el móvil guarda para poder vincular después su pedido a la tarjeta
        return p["id"]

    def estado(self, pid, estado):
        c, j = self.admin.json("POST", "/api/pedido/estado", {"id": pid, "estado": estado})
        self.assertEqual(c, 200, j)
        return j

    def tarjeta(self, tid):
        c, j = Cliente().json("GET", "/api/tarjeta?t=" + tid)
        self.assertEqual(c, 200)
        return j

    def simulador(self):
        c, j = self.admin.json("GET", "/api/wallet/simulador")
        self.assertEqual(c, 200, j)
        return j

    def esperar_push(self, token, n=1):
        import time
        for _ in range(50):
            hechos = [x for x in self.simulador()["registro"] if x["canal"] == "apns" and x["push_token"] == token]
            if len(hechos) >= n:
                return hechos
            time.sleep(0.1)
        self.fail("el push simulado no llegó")

    def test_servido_sella_una_vez_y_canje(self):
        t = self.nueva()
        self.assertEqual(self.tarjeta(t)["sellos"], 0)
        p1 = self.pedido(t)
        self.assertEqual(self.tarjeta(t)["sellos"], 0)                 # recién enviado: aún no es servido
        self.estado(p1, "preparando")
        self.estado(p1, "listo")
        self.assertEqual(self.tarjeta(t)["sellos"], 0)
        self.assertEqual(self.estado(p1, "entregado")["sello"], "sellado")
        self.assertEqual(self.tarjeta(t)["sellos"], 1)
        # deshacer y volver a servir el mismo pedido: no duplica
        self.estado(p1, "listo")
        self.assertEqual(self.estado(p1, "entregado")["sello"], "repetido")
        self.assertEqual(self.tarjeta(t)["sellos"], 1)
        # pedido sin tarjeta: no hay sello; con una tarjeta inventada: el pedido va igual pero sin vínculo
        self.assertIsNone(self.estado(self.pedido(), "entregado")["sello"])
        self.assertIsNone(self.estado(self.pedido("A" * 16), "entregado")["sello"])
        # canje: aún faltan sellos (meta 2) -> 409; con el segundo sello -> premio -> canje -> 0 y no se repite
        self.assertEqual(self.admin.json("POST", "/api/sellos/canjear", {"t": t})[0], 409)
        self.estado(self.pedido(t), "entregado")
        e = self.tarjeta(t)
        self.assertEqual((e["sellos"], e["premios_disponibles"]), (2, 1))
        c, j = self.admin.json("POST", "/api/sellos/canjear", {"t": f"{URL}/tarjeta?t={t}"})     # la caja puede leer el enlace del QR
        self.assertEqual((c, j["resultado"], j["sellos"]), (200, "canjeado", 0), j)
        self.assertEqual(self.admin.json("POST", "/api/sellos/canjear", {"t": t})[0], 409)
        self.assertEqual(self.tarjeta(t)["sellos"], 0)
        # la caja necesita sesión
        self.assertEqual(Cliente().json("POST", "/api/sellos/canjear", {"t": t})[0], 401)
        self.assertEqual(Cliente().json("PUT", "/api/sellos/config", {})[0], 401)
        self.assertEqual(Cliente().json("GET", "/api/sellos/tarjeta?t=" + t)[0], 401)

    def test_sellar_en_caja_e_importe_minimo(self):
        t = self.nueva()
        self.assertEqual(self.admin.json("POST", "/api/sellos/sellar", {"t": t, "importe": 7.5})[1]["sellos"], 1)
        self.ajustes(meta=2, minimo=50)
        try:
            self.assertEqual(self.admin.json("POST", "/api/sellos/sellar", {"t": t, "importe": 7.5})[0], 409)
            self.estado(self.pedido(t), "entregado")
            self.assertEqual(self.tarjeta(t)["sellos"], 1)            # el pedido no llega al mínimo: sin sello
        finally:
            self.ajustes(meta=2, minimo=0)
        c, j = self.admin.json("GET", "/api/sellos/tarjeta?t=" + t)
        self.assertEqual((c, [m["origen"] for m in j["movimientos"]]), (200, ["caja"]))
        self.assertEqual(self.admin.json("GET", "/api/sellos/tarjeta?t=nope")[0], 404)

    def test_programa_desactivado(self):
        t = self.nueva()
        self.ajustes(meta=2, minimo=0, activo=False)
        try:
            self.assertEqual(Cliente().json("POST", "/api/tarjeta")[0], 404)
            self.estado(self.pedido(t), "entregado")
            self.assertEqual(self.tarjeta(t)["sellos"], 0)
        finally:
            self.ajustes(meta=2, minimo=0)

    def test_pedido_servido_y_vinculado_despues(self):
        t = self.nueva()
        p = self.pedido()
        self.estado(p, "entregado")
        tk = self.tokens[p]
        self.assertEqual(Cliente().json("POST", "/api/pedido/tarjeta", {"id": p, "tarjeta": t})[0], 403)   # sin el token del pedido no vale
        c, j = Cliente().json("POST", "/api/pedido/tarjeta", {"id": p, "token": tk, "tarjeta": t})
        self.assertEqual((c, j["sello"]), (200, "sellado"), j)
        self.assertEqual(Cliente().json("POST", "/api/pedido/tarjeta", {"id": p, "token": tk, "tarjeta": t})[1]["sello"], None)   # ya vinculado: nada
        self.assertEqual(Cliente().json("POST", "/api/pedido/tarjeta", {"id": p, "token": tk, "tarjeta": self.nueva()})[0], 409)
        self.assertEqual(self.tarjeta(t)["sellos"], 1)

    def test_pkpass_firmado_y_actualizacion_apple(self):
        import hashlib, io, re, subprocess, tempfile, time, zipfile
        t = self.nueva()
        cl = Cliente()
        c, datos, h = cl.pedir("GET", f"/tarjeta/{t}.pkpass")
        self.assertEqual((c, h["Content-Type"]), (200, "application/vnd.apple.pkpass"))
        z = zipfile.ZipFile(io.BytesIO(datos))
        manifiesto, pase = z.read("manifest.json"), json.loads(z.read("pass.json"))
        self.assertEqual(pase["serialNumber"], t)
        self.assertTrue(pase["webServiceURL"].startswith("https://localhost:"), pase["webServiceURL"])
        for n, sha in json.loads(manifiesto).items():
            self.assertEqual(hashlib.sha1(z.read(n)).hexdigest(), sha, n)
        # la firma se comprueba FUERA de nuestro código, con openssl y la CA de prueba que da el simulador
        with tempfile.TemporaryDirectory() as d:
            for n, b in (("m.json", manifiesto), ("sig", z.read("signature")), ("ca.pem", self.simulador()["apple_ca"].encode())):
                escribir(f"{d}/{n}", b)
            r = subprocess.run(["openssl", "smime", "-verify", "-binary", "-inform", "DER", "-in", f"{d}/sig", "-content", f"{d}/m.json",
                                "-CAfile", f"{d}/ca.pem", "-purpose", "any", "-out", "/dev/null"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            escribir(f"{d}/m.json", manifiesto + b" ")        # un byte más y la firma deja de valer
            r = subprocess.run(["openssl", "smime", "-verify", "-binary", "-inform", "DER", "-in", f"{d}/sig", "-content", f"{d}/m.json",
                                "-CAfile", f"{d}/ca.pem", "-purpose", "any", "-out", "/dev/null"], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
        # servicio web: registro del móvil (con y sin la clave de autenticación del pase)
        tipo, auth, dev, push = pase["passTypeIdentifier"], pase["authenticationToken"], "movil-" + t, "push-" + t
        ruta = f"/wallet/apple/v1/devices/{dev}/registrations/{tipo}/{t}"
        con = lambda a: {"Authorization": "ApplePass " + a}
        self.assertEqual(cl.pedir("POST", ruta, {"pushToken": push}, con("mala"))[0], 401)
        self.assertEqual(cl.pedir("POST", ruta, {"pushToken": push})[0], 401)
        self.assertEqual(cl.pedir("POST", ruta, {"pushToken": push}, con(auth))[0], 201)
        self.assertEqual(cl.pedir("POST", ruta, {"pushToken": push}, con(auth))[0], 200)
        lista = f"/wallet/apple/v1/devices/{dev}/registrations/{tipo}"
        c, b, _ = cl.pedir("GET", lista)
        self.assertEqual(c, 200)
        marca0 = json.loads(b)["lastUpdated"]
        self.assertEqual(cl.pedir("GET", lista + "?passesUpdatedSince=" + marca0)[0], 204)    # nada nuevo
        # un pedido servido -> sello -> push al móvil -> lista de cambios -> pase nuevo con el sello
        pe = f"/wallet/apple/v1/passes/{tipo}/{t}"
        c, _, h = cl.pedir("GET", pe, None, con(auth))
        self.assertEqual(c, 200)
        visto = h["Last-Modified"]
        self.assertEqual(cl.pedir("GET", pe, None, {**con(auth), "If-Modified-Since": visto})[0], 304)
        time.sleep(1.1)                                           # Last-Modified tiene resolución de segundos
        self.estado(self.pedido(t), "entregado")
        self.esperar_push(push)
        c, b, _ = cl.pedir("GET", lista + "?passesUpdatedSince=" + marca0)
        self.assertEqual((c, json.loads(b)["serialNumbers"]), (200, [t]))
        c, nuevo, h = cl.pedir("GET", pe, None, {**con(auth), "If-Modified-Since": visto})
        self.assertEqual(c, 200)
        self.assertEqual(json.loads(zipfile.ZipFile(io.BytesIO(nuevo)).read("pass.json"))["storeCard"]["headerFields"][0]["value"], "1 / 2")
        self.assertEqual(cl.pedir("GET", pe, None, con("mala"))[0], 401)
        # baja del registro: ya no hay push
        self.assertEqual(cl.pedir("DELETE", ruta, None, con(auth))[0], 200)
        self.assertEqual(cl.pedir("GET", lista)[0], 204)
        self.assertEqual(cl.pedir("POST", "/wallet/apple/v1/log", {"logs": ["x"]})[0], 200)

    def test_google_enlace_y_actualizacion(self):
        import base64, subprocess, tempfile
        t = self.nueva()
        # urllib seguiría la redirección a pay.google.com (sin red en la prueba): se pide sin seguirla
        import http.client
        host, puerto = URL.split("//")[1].rsplit(":", 1)
        con = http.client.HTTPSConnection(host, int(puerto), context=CTX, timeout=10)
        con.request("GET", f"/tarjeta/{t}/google")
        r = con.getresponse()
        self.assertEqual(r.status, 302)
        enlace = r.getheader("Location")
        con.close()
        self.assertTrue(enlace.startswith("https://pay.google.com/gp/v/save/"))
        cab, cuerpo, firma = enlace.rsplit("/", 1)[1].split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)
        claims = json.loads(base64.urlsafe_b64decode(pad(cuerpo)))
        self.assertEqual(claims["payload"]["loyaltyObjects"][0]["barcode"]["value"], t)
        with tempfile.TemporaryDirectory() as d:
            escribir(f"{d}/pub.pem", self.simulador()["google_clave_publica"])
            escribir(f"{d}/firma", base64.urlsafe_b64decode(pad(firma)))
            v = lambda datos: subprocess.run(["openssl", "dgst", "-sha256", "-verify", f"{d}/pub.pem", "-signature", f"{d}/firma"], input=datos, capture_output=True).returncode
            self.assertEqual(v(f"{cab}.{cuerpo}".encode()), 0)
            self.assertNotEqual(v(f"{cab}.{cuerpo}x".encode()), 0)
        # un sello actualiza el objeto de Google (cliente simulado)
        self.estado(self.pedido(t), "entregado")
        import time
        for _ in range(50):
            parches = [x for x in self.simulador()["registro"] if x["canal"] == "google" and x["objeto"].endswith("." + t)]
            if parches:
                break
            time.sleep(0.1)
        self.assertTrue(parches, "no se actualizó el objeto de Google")
        self.assertEqual(parches[-1]["cuerpo"]["loyaltyPoints"]["balance"]["string"], "1 / 2")

    def test_pagina_y_rutas_publicas(self):
        cl = Cliente()
        t = self.nueva()
        c, b, _ = cl.pedir("GET", "/tarjeta?t=" + t)
        self.assertEqual(c, 200)
        self.assertNotIn(b"{{", b)
        self.assertEqual(cl.json("GET", "/api/tarjeta?t=" + "x" * 16)[0], 404)
        self.assertEqual(cl.pedir("GET", "/tarjeta/" + "x" * 16 + ".pkpass")[0], 404)
        c, j = cl.json("GET", "/api/sellos")
        self.assertEqual((c, j["canales"]["apple"], j["canales"]["google"]), (200, "prueba", "prueba"))
        self.assertEqual(cl.pedir("GET", "/api/wallet/simulador")[0], 401)
        self.assertNotIn("auth", json.dumps(self.tarjeta(t)).lower())


class Promociones(unittest.TestCase):
    """promoción redactada en el backoffice -> envío simulado -> solo reciben los que dieron permiso, la baja se respeta y queda registro."""
    setUp = Permiso.setUp
    ficha = Permiso.ficha
    admin_token = Permiso.admin_token

    def cliente(self, nombre, permiso=True, tarjeta=False):
        import time
        email = f"{nombre}{int(time.time() * 1000)}@example.com"
        cuerpo = {"mesa": self.mesa, "lineas": [{"pid": self.pid, "rm": [], "ex": []}]}
        tid = None
        if tarjeta:
            tid = Cliente().json("POST", "/api/tarjeta")[1]["id"]
            cuerpo["tarjeta"] = tid
        if permiso:
            cuerpo["permiso"] = {"email": email, "version": Cliente().json("GET", "/api/permiso")[1]["version"]}
        self.assertEqual(Cliente().json("POST", "/api/pedido", cuerpo)[0], 200)
        if permiso and DOBLE:
            self.assertEqual(Cliente().json("POST", "/api/confirmar", {"token": token_confirmacion(self.admin, email)})[0], 200)
        return email, tid

    def esperar_envio(self, pid):
        import time
        for _ in range(100):
            c, j = self.admin.json("GET", "/api/promociones")
            p = next(x for x in j["promociones"] if x["id"] == pid)
            if p["estado"] == "enviada":
                return p
            time.sleep(0.1)
        self.fail("la promoción no terminó de enviarse")

    def correos(self, emails):
        c, j = self.admin.json("GET", "/api/promociones/simulador")
        self.assertEqual(c, 200)
        return [m for m in j["correos"] if m["para"] in emails and m["asunto"].startswith("Publicidad:")]   # sin los de confirmación

    def test_envio_solo_a_quien_dio_permiso(self):
        import re
        ana, t_ana = self.cliente("ana", tarjeta=True)
        beto, _ = self.cliente("beto")
        cleo, t_cleo = self.cliente("cleo", tarjeta=True)
        sin, t_sin = self.cliente("sin", permiso=False, tarjeta=True)
        todos = {ana, beto, cleo, sin}
        self.assertEqual(Cliente().pedir("GET", "/api/promociones")[0], 401)
        self.assertEqual(Cliente().pedir("POST", "/api/promociones/enviar", {"id": 1})[0], 401)
        # cleo se da de baja antes de que se envíe nada
        self.assertEqual(Cliente().json("POST", "/api/baja", {"token": self.admin_token(cleo)})[0], 200)
        self.assertIsNone(self.ficha(sin), "sin permiso no hay ficha")
        # validaciones
        self.assertEqual(self.admin.json("POST", "/api/promociones", {"titulo": "x", "texto": "hola mundo", "canales": ["email"]})[0], 400)
        self.assertEqual(self.admin.json("POST", "/api/promociones", {"titulo": "Martes 2x1", "texto": "hola mundo", "canales": ["sms"]})[0], 400)
        c, j = self.admin.json("POST", "/api/promociones", {"titulo": "Martes 2x1", "texto": "Dos platos por el precio de uno.", "canales": ["email", "wallet"]})
        self.assertEqual(c, 200, j)
        pid = j["id"]
        c, j = self.admin.json("POST", "/api/promociones/enviar", {"id": pid})
        self.assertEqual(c, 202, j)
        p = self.esperar_envio(pid)
        self.assertEqual(self.admin.json("POST", "/api/promociones/enviar", {"id": pid})[0], 409, "no se envía dos veces")
        # correo: solo ana y beto, con «Publicidad», su enlace de baja y la cabecera de baja
        recibidos = self.correos(todos)
        self.assertEqual(sorted(m["para"] for m in recibidos), sorted([ana, beto]))
        for m in recibidos:
            tok = self.admin_token(m["para"])
            self.assertTrue(m["asunto"].startswith("Publicidad: "))
            self.assertRegex(m["texto"], r"/baja\?t=" + tok)
            self.assertEqual(m["cabeceras"]["List-Unsubscribe"].strip("<>").split("t=")[1], tok)
        # registro: qué, a quién, cuándo
        c, reg = self.admin.json("GET", f"/api/promociones/registro?id={pid}")
        self.assertEqual(c, 200)
        mios = [e for e in reg["envios"] if e["destino"] in todos or e["destino"] in (t_ana, t_cleo, t_sin)]
        self.assertEqual(sorted((e["canal"], e["destino"]) for e in mios), sorted([("email", ana), ("email", beto), ("wallet", t_ana)]))
        self.assertTrue(all(e["resultado"] == "enviado" and re.match(r"^\d{4}-\d\d-\d\dT", e["fecha"]) for e in mios))
        # Wallet: el aviso llegó a la tarjeta de ana y a ninguna más
        c, s = self.admin.json("GET", "/api/wallet/simulador")
        self.assertEqual(c, 200)
        para_ana = [x for x in s["registro"] if t_ana in json.dumps(x) and "Martes 2x1" in json.dumps(x)]
        self.assertTrue(para_ana, "el aviso llega a la tarjeta de ana")
        for t in (t_cleo, t_sin):
            self.assertFalse([x for x in s["registro"] if t in json.dumps(x) and "Martes 2x1" in json.dumps(x)])
        self.assertEqual(p["estado"], "enviada")
        # ana se da de baja con el enlace de SU correo; la siguiente promoción ya no le llega
        self.assertEqual(Cliente().json("POST", "/api/baja", {"token": self.admin_token(ana)})[0], 200)
        pid2 = self.admin.json("POST", "/api/promociones", {"titulo": "Jueves de tapas", "texto": "Tapa gratis con cada caña.", "canales": ["email", "wallet"]})[1]["id"]
        self.assertEqual(self.admin.json("POST", "/api/promociones/enviar", {"id": pid2})[0], 202)
        self.esperar_envio(pid2)
        self.assertEqual([m["para"] for m in self.correos(todos) if m["asunto"].endswith("Jueves de tapas")], [beto])
        reg2 = self.admin.json("GET", f"/api/promociones/registro?id={pid2}")[1]["envios"]
        self.assertEqual([e["destino"] for e in reg2 if e["destino"] in todos or e["destino"] in (t_ana, t_cleo, t_sin)], [beto])

    def test_borrador_se_borra_y_enviada_no(self):
        pid = self.admin.json("POST", "/api/promociones", {"titulo": "Borrador", "texto": "Texto del borrador.", "canales": ["email"]})[1]["id"]
        self.assertEqual(self.admin.json("DELETE", f"/api/promociones?id={pid}")[0], 200)
        self.assertEqual(self.admin.json("POST", "/api/promociones/enviar", {"id": pid})[0], 404)


@unittest.skipUnless(os.environ.get("CARTA_FRENO") == "1", "la lanza contenedor.sh al final: bloquea la IP de las pruebas 10 minutos")
class Freno(unittest.TestCase):
    def test_cf_connecting_ip_inventada_no_evade_el_freno_del_login(self):
        # Caddy sin Cloudflare delante: variar CF-Connecting-IP en cada intento no debe dar un cupo nuevo
        codigos = [Cliente().pedir("POST", "/api/login", {"clave": "mala"}, {"CF-Connecting-IP": f"8.8.8.{i}"})[0] for i in range(10)]
        self.assertIn(429, codigos, codigos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
