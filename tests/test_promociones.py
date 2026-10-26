# SPDX-License-Identifier: EUPL-1.2
"""Promociones (LSSI art. 21), sin red y con simuladores de Brevo, Apple y Google:  python -m unittest tests.test_promociones -v
Usan una carpeta temporal (CARTA_RESTAURANTES): no tocan restaurantes/. Necesitan openssl (viene en la imagen Docker)."""
import json, os, re, shutil, sys, tempfile, unittest, uuid

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="promos-")
os.environ.update(CARTA_RESTAURANTES=TMP, RESTAURANTE="demo", WALLET_MODO="prueba", CORREO_MODO="prueba")
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import clientes, correo, idiomas, promociones, sellos, wallet, wallet_apple  # noqa: E402

BASE = "https://carta.prueba"
HAY_OPENSSL = bool(shutil.which("openssl"))


def setUpModule():
    if not os.path.isfile(os.path.join(sellos.restaurante.DIR, "marca.json")):
        nuevo_restaurante.crear(sellos.restaurante.NOMBRE, "Bar Demo", raiz=sellos.restaurante.RAIZ)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


@unittest.skipUnless(HAY_OPENSSL, "hace falta openssl")
def alta_confirmada(email, **kw):
    """Alta como la deja el doble opt-in: solicitud pendiente + clic del titular en el enlace del correo. Devuelve el id del cliente."""
    with clientes.conectar() as con:   # lo anterior de esa dirección queda fuera de la hora de espera
        con.execute("UPDATE solicitudes SET creada='2000-01-01T00:00:00+00:00' WHERE cliente_id IN (SELECT id FROM clientes WHERE email=?)", (email,))
    cid, token = clientes.solicitar_alta(email, **kw)
    if token:
        assert clientes.confirmar(token)
    return cid


class Promociones(unittest.TestCase):
    def setUp(self):
        self.s = uuid.uuid4().hex[:8]   # otros módulos de prueba comparten la carpeta: cada prueba usa sus propios correos
        os.environ["CORREO_MODO"] = "prueba"

    def alta(self, nombre, con_tarjeta=False, version=None):
        """Cliente con permiso (como si hubiera marcado la casilla al pedir). Devuelve (id, correo, tarjeta, token)."""
        email = f"{nombre}-{self.s}@promo.test"
        if version:
            antes, clientes.TEXTO_VERSION = clientes.TEXTO_VERSION, version
        try:
            cid = alta_confirmada(email)
        finally:
            if version:
                clientes.TEXTO_VERSION = antes
        tid = None
        if con_tarjeta:
            tid = sellos.crear_tarjeta()["id"]
            clientes.vincular_tarjeta(cid, tid)
            sellos.registrar_dispositivo("movil-" + nombre + self.s, "push-" + nombre + self.s, tid)
        return cid, email, tid, clientes.ficha(cid) and self.token(email)

    def token(self, email):
        import sqlite3
        return sqlite3.connect(clientes.DB).execute("select token_baja from clientes where email=?", (email,)).fetchone()[0]

    def mios(self):
        return [m for m in correo.BUZON if m["para"].endswith(f"-{self.s}@promo.test")]

    def enviar(self, canales=("email", "wallet"), titulo="Martes 2x1"):
        pid = promociones.crear(titulo, "Dos platos por el precio de uno.\nHasta el viernes.", list(canales))
        self.assertTrue(promociones.ejecutar(pid, BASE))
        return pid

    def test_alta_directa_recibe_promocion_con_enlace_de_baja(self):
        """Modo por defecto (sin CONFIRMACION_DOBLE): quien marca la casilla recibe la promoción y cada mensaje lleva su enlace de baja."""
        antes = os.environ.pop("CONFIRMACION_DOBLE", None)
        try:
            email = f"directo-{self.s}@promo.test"
            clientes.registrar_alta(email)
        finally:
            if antes is not None:
                os.environ["CONFIRMACION_DOBLE"] = antes
        self.enviar(canales=("email",))
        m = [x for x in self.mios() if x["para"] == email]
        self.assertEqual(len(m), 1)
        tok = self.token(email)
        self.assertIn(f"{BASE}/baja?t={tok}", m[0]["texto"])
        self.assertEqual(m[0]["cabeceras"]["List-Unsubscribe"], f"<{BASE}/baja?t={tok}>")

    def test_solo_reciben_los_que_dieron_permiso(self):
        _, ana, t_ana, tok_ana = self.alta("ana", con_tarjeta=True)
        _, beto, _, _ = self.alta("beto")                                  # permiso sin tarjeta: solo correo
        _, cleo, t_cleo, _ = self.alta("cleo", con_tarjeta=True)
        self.assertTrue(clientes.registrar_baja(self.token(cleo)))         # se da de baja antes de enviar
        _, dani, t_dani, _ = self.alta("dani", con_tarjeta=True, version="1")   # su permiso era solo de correo
        t_anonima = sellos.crear_tarjeta()["id"]                           # tarjeta sin cliente: sin permiso de nada
        sellos.registrar_dispositivo("movil-anonimo" + self.s, "push-anonimo" + self.s, t_anonima)
        antes = len(wallet.REGISTRO)

        pid = self.enviar()

        para = sorted(m["para"] for m in self.mios())
        self.assertEqual(para, sorted([ana, beto, dani]), "el correo solo llega a quien tiene permiso vigente")
        envios = [e for e in promociones.registro(pid) if e["destino"] in (ana, beto, cleo, dani, t_ana, t_cleo, t_dani, t_anonima)]
        self.assertEqual(sorted((e["canal"], e["destino"]) for e in envios),
                         sorted([("email", ana), ("email", beto), ("email", dani), ("wallet", t_ana)]),
                         "el registro apunta exactamente lo enviado")
        self.assertTrue(all(e["resultado"] == "enviado" for e in envios))
        self.assertTrue(all(re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$", e["fecha"]) for e in envios))
        # Wallet: solo la tarjeta de Ana (permiso vigente que cubre Wallet) recibió push y mensaje
        nuevos = list(wallet.REGISTRO)[antes:]
        self.assertEqual([x["push_token"] for x in nuevos if x["canal"] == "apns" and x["push_token"].endswith(self.s)], ["push-ana" + self.s])
        # el pase de Ana lleva la promoción y su enlace de baja; el de Dani, nada
        a = sellos.estado(t_ana)["aviso"]
        self.assertEqual(a["titulo"], "Martes 2x1")
        self.assertEqual(a["baja_url"], f"{BASE}/baja?t={tok_ana}")
        campos = wallet_apple.pass_json(sellos.estado(t_ana), "x", BASE, sellos.restaurante.marca())["storeCard"]["backFields"]
        self.assertIn("Martes 2x1", [c["label"] for c in campos])
        self.assertIn(f"{BASE}/baja?t={tok_ana}", [c.get("attributedValue", "") for c in campos if c["key"] == "baja"][0])
        self.assertIsNone(sellos.estado(t_dani)["aviso"])
        self.assertIsNone(sellos.estado(t_anonima)["aviso"])
        self.assertIsNone(sellos.estado(t_cleo)["aviso"])
        google = [x for x in nuevos if x["canal"] == "google" and x["operacion"] == "anadir_mensaje"]
        self.assertEqual(len(google), 1)
        self.assertTrue(google[0]["objeto"].endswith(t_ana))
        self.assertEqual(google[0]["mensaje"]["messageType"], "TEXT_AND_NOTIFY")
        self.assertIn(f"{BASE}/baja?t={tok_ana}", google[0]["mensaje"]["body"])

    def test_cada_correo_lleva_baja_y_se_identifica_como_publicidad(self):
        _, ana, _, tok_ana = self.alta("ana")
        _, beto, _, tok_beto = self.alta("beto")
        self.enviar(canales=("email",))
        for m, tok in ((next(m for m in self.mios() if m["para"] == ana), tok_ana), (next(m for m in self.mios() if m["para"] == beto), tok_beto)):
            self.assertTrue(m["asunto"].startswith("Publicidad: "))
            self.assertIn(f"{BASE}/baja?t={tok}", m["texto"])
            self.assertIn(f"{BASE}/baja?t={tok}", m["html"])
            self.assertEqual(m["cabeceras"]["List-Unsubscribe"], f"<{BASE}/baja?t={tok}>")
            self.assertIn("Bar Demo", m["texto"])
            self.assertIn("marcaste la casilla", m["texto"])      # por qué lo recibe
        # el enlace de cada correo es el suyo, no el de otro
        self.assertNotIn(tok_beto, next(m for m in self.mios() if m["para"] == ana)["texto"])

    def test_correo_en_el_idioma_del_cliente_con_baja_en_cada_uno(self):
        esperado = {"es": ("Publicidad: ", "Darme de baja"), "en": ("Advertising: ", "Unsubscribe"),
                    "ca": ("Publicitat: ", "Donar-me de baixa"), "zh": ("广告：", "退订"),
                    "fr": ("Publicité\u00a0: ", "Me désabonner"), "de": ("Werbung: ", "abmelden"), "it": ("Pubblicità: ", "Annulla l’iscrizione"),
                    "pt": ("Publicidade: ", "Cancelar a subscrição")}
        tokens = {}
        for idioma in idiomas.IDIOMAS:
            email = f"{idioma}-{self.s}@promo.test"
            alta_confirmada(email, idioma=idioma)
            tokens[idioma] = self.token(email)
        self.enviar(canales=("email",))
        self.assertEqual(len(self.mios()), len(idiomas.IDIOMAS))
        for m in self.mios():
            idioma = m["para"].split("-")[0]
            asunto, baja = esperado[idioma]
            self.assertTrue(m["asunto"].startswith(asunto), m["asunto"])
            self.assertIn(baja, m["texto"])
            self.assertIn(baja, m["html"])
            self.assertIn(f'<html lang="{idioma}">', m["html"])
            self.assertIn(f"{BASE}/baja?t={tokens[idioma]}", m["texto"])
            self.assertEqual(m["cabeceras"]["List-Unsubscribe"], f"<{BASE}/baja?t={tokens[idioma]}>")
            self.assertIn("Bar Demo", m["texto"])
        self.assertFalse([m for m in self.mios() if "{" in m["texto"]])

    def test_pase_y_aviso_de_wallet_en_el_idioma_del_cliente(self):
        email = f"zhu-{self.s}@promo.test"
        cid = alta_confirmada(email, idioma="zh")
        tid = sellos.crear_tarjeta("es")["id"]
        clientes.vincular_tarjeta(cid, tid)                       # la tarjeta pasa al idioma del cliente
        sellos.registrar_dispositivo("movil-zhu" + self.s, "push-zhu" + self.s, tid)
        self.assertEqual(sellos.estado(tid)["idioma"], "zh")
        antes = len(wallet.REGISTRO)
        self.enviar(canales=("wallet",))
        msg = [x for x in list(wallet.REGISTRO)[antes:] if x["canal"] == "google" and x["operacion"] == "anadir_mensaje"][0]["mensaje"]
        self.assertIn("退订", msg["body"])
        campos = wallet_apple.pass_json(sellos.estado(tid), "x", BASE, sellos.restaurante.marca(), "zh")["storeCard"]["backFields"]
        self.assertIn("退订优惠信息", [c["value"] for c in campos if c["key"] == "baja"])
        self.assertTrue(clientes.registrar_baja(self.token(email)))   # no deja un cliente con Wallet para las demás pruebas

    def test_correo_de_confirmacion_con_la_url_configurada_y_en_el_idioma(self):
        antes = os.environ.get("URL_PUBLICA")
        os.environ["URL_PUBLICA"] = "https://bar.example/"
        try:
            for idioma, trozo in (("es", "Confirma que quieres"), ("en", "Confirm that you want"), ("ca", "Confirma que vols"), ("zh", "请确认")):
                email = f"conf-{idioma}-{self.s}@promo.test"
                _, token = clientes.solicitar_alta(email, idioma=idioma)
                self.assertTrue(promociones.enviar_confirmacion(email, token, idioma))
                m = [x for x in correo.BUZON if x["para"] == email][-1]
                self.assertIn(trozo, m["asunto"])
                self.assertIn(f"https://bar.example/confirmar?t={token}&lang={idioma}", m["texto"])
                self.assertIn(f"https://bar.example/confirmar?t={token}&amp;lang={idioma}", m["html"])
                self.assertNotIn("Publicidad", m["asunto"])
                self.assertFalse(clientes.apto_marketing(email))      # el correo solo ofrece el enlace: no confirma nada
            del os.environ["URL_PUBLICA"]
            self.assertFalse(promociones.enviar_confirmacion(f"x-{self.s}@promo.test", "t" * 24))   # sin URL pública no se inventa una
        finally:
            os.environ.pop("URL_PUBLICA", None)
            if antes is not None:
                os.environ["URL_PUBLICA"] = antes

    def test_sin_canal_de_correo_no_se_manda_confirmacion(self):
        os.environ["URL_PUBLICA"] = "https://bar.example"
        os.environ.pop("CORREO_MODO", None)
        antes = {k: os.environ.pop(k, None) for k in ("BREVO_API_KEY", "BREVO_REMITENTE")}
        try:
            self.assertFalse(promociones.enviar_confirmacion(f"nada-{self.s}@promo.test", "t" * 24))
        finally:
            os.environ.pop("URL_PUBLICA", None)
            for k, v in antes.items():
                if v is not None:
                    os.environ[k] = v

    def test_la_baja_se_respeta_y_no_se_vuelve_a_enviar(self):
        _, ana, _, tok_ana = self.alta("ana")
        _, beto, _, tok_beto = self.alta("beto")
        self.enviar(canales=("email",), titulo="Primera")
        self.assertEqual(sorted(m["para"] for m in self.mios()), sorted([ana, beto]))
        self.assertTrue(clientes.registrar_baja(tok_ana))             # Ana pulsa el enlace de baja del correo recibido
        correo.BUZON.clear()
        pid = self.enviar(canales=("email",), titulo="Segunda")
        self.assertEqual([m["para"] for m in self.mios()], [beto])
        self.assertEqual([e["destino"] for e in promociones.registro(pid) if e["destino"].endswith(f"-{self.s}@promo.test")], [beto])
        # si vuelve a marcar la casilla, vuelve a recibir
        alta_confirmada(ana)
        correo.BUZON.clear()
        self.enviar(canales=("email",), titulo="Tercera")
        self.assertEqual(sorted(m["para"] for m in self.mios()), sorted([ana, beto]))

    def test_baja_que_llega_durante_el_envio_se_respeta(self):
        _, ana, _, _ = self.alta("ana")
        _, beto, _, tok_beto = self.alta("beto")
        original = correo.enviar
        orden = []

        def enviar_y_dar_de_baja_al_otro(m):
            orden.append(m["para"])
            if len(orden) == 1:   # al primero le llega y mientras tanto el segundo se da de baja
                clientes.registrar_baja(tok_beto if m["para"] == ana else self.token(ana))
            return original(m)
        correo.enviar = enviar_y_dar_de_baja_al_otro
        try:
            pid = self.enviar(canales=("email",))
        finally:
            correo.enviar = original
        mios = [m for m in orden if m.endswith(f"-{self.s}@promo.test")]
        self.assertEqual(len(mios), 1, "el que se dio de baja durante el envío no recibe")
        self.assertEqual(len([e for e in promociones.registro(pid) if e["destino"] in (ana, beto)]), 1)

    def test_una_promocion_se_envia_una_sola_vez(self):
        self.alta("ana")
        pid = self.enviar(canales=("email",))
        n = len(self.mios())
        self.assertFalse(promociones.ejecutar(pid, BASE), "enviar otra vez la misma promoción no hace nada")
        self.assertEqual(len(self.mios()), n)
        self.assertEqual(promociones.obtener(pid)["estado"], "enviada")
        # una reanudación (tras una caída) no repite a quien ya se le intentó
        import sqlite3
        with sqlite3.connect(promociones.DB) as con:
            con.execute("update promociones set estado='enviando', inicio='2000-01-01T00:00:00+00:00' where id=?", (pid,))
        self.assertTrue(promociones.ejecutar(pid, BASE))
        self.assertEqual(len(self.mios()), n)

    def test_limite_de_avisos_de_wallet_por_tarjeta(self):
        _, ana, t_ana, _ = self.alta("ana", con_tarjeta=True)
        for i in range(promociones.LIMITE_WALLET):
            pid = self.enviar(canales=("wallet",), titulo=f"Promo {i}")
            self.assertEqual([e["resultado"] for e in promociones.registro(pid) if e["destino"] == t_ana], ["enviado"])
        pid = self.enviar(canales=("wallet",), titulo="Una de más")
        self.assertEqual([e["resultado"] for e in promociones.registro(pid) if e["destino"] == t_ana], ["omitido_limite"])
        self.assertEqual(sellos.estado(t_ana)["aviso"]["titulo"], f"Promo {promociones.LIMITE_WALLET - 1}", "el aviso omitido no cambia la tarjeta")

    def test_canal_sin_credenciales_no_se_puede_elegir_y_validaciones(self):
        os.environ["CORREO_MODO"] = ""
        with self.assertRaises(ValueError):
            promociones.crear("Titulo", "Mensaje de prueba", ["email"])
        os.environ["CORREO_MODO"] = "prueba"
        for t, m, c in (("", "Mensaje de prueba", ["email"]), ("Titulo", "", ["email"]), ("Titulo", "x" * 301, ["email"]),
                        ("Titulo", "Mensaje de prueba", []), ("Titulo", "Mensaje de prueba", ["sms"]), ("Titulo", "Mensaje de prueba", "email"),
                        ("Ti\ntulo", "Mensaje de prueba", ["email"]), (None, "Mensaje de prueba", ["email"])):
            with self.assertRaises(ValueError, msg=repr((t, m, c))):
                promociones.crear(t, m, c)

    def test_permiso_antiguo_solo_cubre_correo(self):
        _, _, t, _ = self.alta("dani", con_tarjeta=True, version="1")
        self.assertEqual([d for d in clientes.destinatarios("wallet") if d["tarjeta"] == t], [])
        self.assertEqual(len([d for d in clientes.destinatarios("email") if d["email"].endswith(f"-{self.s}@promo.test")]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
