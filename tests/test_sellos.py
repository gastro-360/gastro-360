# SPDX-License-Identifier: EUPL-1.2
"""Tarjeta de sellos y Wallet (sin red, con certificado y clave de PRUEBA):  python -m unittest tests.test_sellos -v
Usan una carpeta temporal (CARTA_RESTAURANTES): no tocan restaurantes/. Necesitan openssl (viene en la imagen Docker)."""
import base64, io, json, os, shutil, sys, tempfile, unittest, zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="sellos-")
os.environ.update(CARTA_RESTAURANTES=TMP, RESTAURANTE="demo", WALLET_MODO="prueba")
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import idiomas, sellos, tarjeta_web, wallet, wallet_apple, wallet_google  # noqa: E402

HAY_OPENSSL = bool(shutil.which("openssl"))


def setUpModule():
    # con `discover` otro módulo pudo fijar antes la carpeta temporal (y borrarla): se asegura un restaurante de prueba
    if not os.path.isfile(os.path.join(sellos.restaurante.DIR, "marca.json")):
        nuevo_restaurante.crear(sellos.restaurante.NOMBRE, "Bar Demo", raiz=sellos.restaurante.RAIZ)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Sellos(unittest.TestCase):
    def setUp(self):
        sellos.guardar_config({"activo": True, "sellos_meta": 3, "premio": "Un plato gratis", "importe_minimo": 5})

    def test_servido_da_sello_y_no_duplica(self):
        t = sellos.crear_tarjeta()["id"]
        self.assertEqual(sellos.estado(t)["sellos"], 0)
        r, e = sellos.sellar(t, 6.5, "servido", pedido_id="p1")
        self.assertEqual((r, e["sellos"]), ("sellado", 1))
        # el mismo pedido, otra vez «servido»: no suma
        r, e = sellos.sellar(t, 6.5, "servido", pedido_id="p1")
        self.assertEqual((r, e["sellos"]), ("repetido", 1))
        # ni siquiera si lo intenta otra tarjeta
        otra = sellos.crear_tarjeta()["id"]
        self.assertEqual(sellos.sellar(otra, 6.5, "servido", pedido_id="p1")[0], "repetido")
        self.assertEqual(sellos.estado(otra)["sellos"], 0)
        # otro pedido sí
        self.assertEqual(sellos.sellar(t, 6.5, "servido", pedido_id="p2")[1]["sellos"], 2)

    def test_importe_minimo_y_programa_desactivado(self):
        t = sellos.crear_tarjeta()["id"]
        self.assertEqual(sellos.sellar(t, 4.99, "servido", pedido_id="b1")[0], "importe_bajo")
        self.assertEqual(sellos.sellar(t, 5.0, "servido", pedido_id="b2")[0], "sellado")   # justo el mínimo
        sellos.guardar_config({"activo": False, "sellos_meta": 3, "premio": "x", "importe_minimo": 5})
        self.assertEqual(sellos.sellar(t, 9, "servido", pedido_id="b3")[0], "desactivado")
        self.assertEqual(sellos.estado(t)["sellos"], 1)
        # un pedido que no dio sello por el importe puede darlo si luego cumple (no queda «gastado»)
        sellos.guardar_config({"activo": True, "sellos_meta": 3, "premio": "x", "importe_minimo": 1})
        self.assertEqual(sellos.sellar(t, 4.99, "servido", pedido_id="b1")[0], "sellado")
        self.assertEqual(sellos.sellar("no-existe-123456", 9, "servido")[0], "sin_tarjeta")

    def test_canje(self):
        t = sellos.crear_tarjeta()["id"]
        for i in range(2):
            sellos.sellar(t, 6, "servido", pedido_id=f"c{i}")
        ok, e = sellos.canjear(t)
        self.assertFalse(ok)                      # faltan sellos
        self.assertEqual(e["sellos"], 2)
        sellos.sellar(t, 6, "servido", pedido_id="c2")
        self.assertEqual(sellos.estado(t)["premios_disponibles"], 1)
        ok, e = sellos.canjear(t)
        self.assertTrue(ok)
        self.assertEqual((e["sellos"], e["canjes"], e["premios_disponibles"]), (0, 1, 0))
        self.assertFalse(sellos.canjear(t)[0])    # no se puede canjear dos veces
        self.assertEqual([m["tipo"] for m in sellos.movimientos(t)], ["sello"] * 3 + ["canje"])
        self.assertEqual(sellos.movimientos(t)[-1]["detalle"], "Un plato gratis")
        self.assertEqual(sellos.canjear("no-existe-123456"), (False, None))

    def test_tope_y_flujo_sellar_premio_canjear_sellar(self):
        t = sellos.crear_tarjeta()["id"]          # meta = 3
        for i in range(3):
            self.assertEqual(sellos.sellar(t, 6, "caja")[0], "sellado")
        # con el premio disponible no suma más, ni a mano ni al servir un pedido
        for origen, pid in (("caja", None), ("caja", None), ("servido", "p-tope")):
            r, e = sellos.sellar(t, 6, origen, pedido_id=pid)
            self.assertEqual((r, e["sellos"], e["premios_disponibles"]), ("tope", 3, 1))
        self.assertEqual(len(sellos.movimientos(t)), 3)   # el rechazo no deja rastro
        ok, e = sellos.canjear(t)
        self.assertTrue(ok)
        self.assertEqual((e["sellos"], e["premios_disponibles"]), (0, 0))
        r, e = sellos.sellar(t, 6, "caja")        # canjeado: vuelve a sumar
        self.assertEqual((r, e["sellos"]), ("sellado", 1))

    def test_tope_si_baja_la_meta(self):
        t = sellos.crear_tarjeta()["id"]
        for _ in range(3):
            sellos.sellar(t, 6, "caja")
        sellos.guardar_config({"activo": True, "sellos_meta": 2, "premio": "Un plato gratis", "importe_minimo": 5})
        self.assertEqual(sellos.sellar(t, 6, "caja")[0], "tope")   # ya tiene de sobra para el premio

    def test_lista_de_tarjetas_sin_datos_personales(self):
        self.assertEqual(sellos.listar("zzzz-no-existe")["tarjetas"], [])
        t = sellos.crear_tarjeta()["id"]
        sellos.sellar(t, 6, "caja")
        antes = sellos.listar()["total"]
        l = sellos.listar()
        self.assertEqual(l["tarjetas"][0]["id"], t)               # la última usada, la primera
        self.assertEqual(set(l["tarjetas"][0]), {"id", "sellos", "sellos_meta", "premio_disponible", "ultimo_uso"})
        self.assertEqual((l["tarjetas"][0]["sellos"], l["tarjetas"][0]["sellos_meta"]), (1, 3))
        self.assertEqual([x["id"] for x in sellos.listar(t[3:9])["tarjetas"]], [t])
        self.assertEqual(sellos.listar("%zzzz_")["tarjetas"], [])  # los comodines de LIKE se descartan, no se interpretan
        self.assertGreaterEqual(antes, 1)

    def test_config_validada_y_conserva_wallet(self):
        for malo in ({"activo": True, "sellos_meta": 0, "premio": "x", "importe_minimo": 1},
                     {"activo": True, "sellos_meta": 3, "premio": "  ", "importe_minimo": 1},
                     {"activo": True, "sellos_meta": 3, "premio": "x", "importe_minimo": -1},
                     {"activo": "si", "sellos_meta": 3, "premio": "x", "importe_minimo": 1}, None):
            with self.assertRaises(ValueError, msg=repr(malo)):
                sellos.guardar_config(malo)
        with open(sellos.CONFIG, "w", encoding="utf-8") as f:
            json.dump({**sellos.config(), "wallet": {"apple": {"pass_type_id": "pass.x", "team_id": "T"}}}, f)
        sellos.guardar_config({"activo": True, "sellos_meta": 4, "premio": "Café", "importe_minimo": 0})
        self.assertEqual(sellos.config()["wallet"]["apple"]["team_id"], "T")
        self.assertEqual(sellos.config()["sellos_meta"], 4)
        os.remove(sellos.CONFIG)
        self.assertEqual(sellos.config()["sellos_meta"], 8)   # sin archivo, valores por defecto

    def test_codigo_de_caja(self):
        t = sellos.crear_tarjeta()["id"]
        self.assertEqual(sellos.extraer_id(f" {t} "), t)
        self.assertEqual(sellos.extraer_id(f"https://carta.ejemplo.es/tarjeta?t={t}"), t)
        for malo in ("", "corto", t + "x", None, 5, "../../etc/passwd"):
            self.assertIsNone(sellos.extraer_id(malo))

    def test_dispositivos_apple(self):
        t = sellos.crear_tarjeta()["id"]
        self.assertTrue(sellos.registrar_dispositivo("dev1", "tokenA", t))
        self.assertFalse(sellos.registrar_dispositivo("dev1", "tokenB", t))      # ya estaba: se cambia el token
        self.assertEqual(sellos.push_tokens(t), ["tokenB"])
        ids, marca = sellos.tarjetas_de_dispositivo("dev1")
        self.assertEqual(ids, [t])
        self.assertEqual(sellos.tarjetas_de_dispositivo("dev1", marca), ([], None))   # nada nuevo desde esa marca
        sellos.sellar(t, 6, "servido", pedido_id="d1")
        self.assertEqual(sellos.tarjetas_de_dispositivo("dev1", marca)[0], [t])       # el sello la hace «actualizada»
        sellos.quitar_dispositivo("dev1", t)
        self.assertEqual(sellos.push_tokens(t), [])


@unittest.skipUnless(HAY_OPENSSL, "hace falta openssl")
class WalletApple(unittest.TestCase):
    def test_pkpass_se_genera_y_la_firma_verifica(self):
        t = sellos.crear_tarjeta()["id"]
        sellos.sellar(t, 6, "servido", pedido_id="a1")
        datos = wallet_apple.construir(t, "https://carta.ejemplo.es")
        z = zipfile.ZipFile(io.BytesIO(datos))
        self.assertTrue({"pass.json", "manifest.json", "signature", "icon.png", "icon@2x.png", "logo.png"} <= set(z.namelist()))
        p = json.loads(z.read("pass.json"))
        self.assertEqual(p["serialNumber"], t)
        self.assertEqual(p["authenticationToken"], sellos.auth_token(t))
        self.assertEqual(p["webServiceURL"], "https://carta.ejemplo.es/wallet/apple")
        self.assertEqual(p["barcodes"][0]["message"], t)
        self.assertEqual(p["storeCard"]["headerFields"][0]["value"], "1 / 3")
        self.assertTrue(z.read("icon.png").startswith(b"\x89PNG"))
        ok, motivo = wallet_apple.verificar(datos, wallet_apple.ca_publica())
        self.assertTrue(ok, motivo)

    def test_la_verificacion_rechaza_lo_manipulado(self):
        t = sellos.crear_tarjeta()["id"]
        datos = wallet_apple.construir(t, "https://carta.ejemplo.es")
        ca = wallet_apple.ca_publica()

        def cambiar(nombre, nuevo):
            salida = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(datos)) as z, zipfile.ZipFile(salida, "w") as o:
                for n in z.namelist():
                    o.writestr(n, nuevo if n == nombre else z.read(n))
            return salida.getvalue()
        pj = json.loads(zipfile.ZipFile(io.BytesIO(datos)).read("pass.json"))
        pj["storeCard"]["headerFields"][0]["value"] = "99 / 3"
        self.assertFalse(wallet_apple.verificar(cambiar("pass.json", json.dumps(pj).encode()), ca)[0])          # el hash ya no cuadra
        self.assertFalse(wallet_apple.verificar(cambiar("manifest.json", b"{}"), ca)[0])                         # manifiesto cambiado
        firma = bytearray(zipfile.ZipFile(io.BytesIO(datos)).read("signature"))
        firma[-5] ^= 0xFF
        self.assertFalse(wallet_apple.verificar(cambiar("signature", bytes(firma)), ca)[0])                       # firma corrupta
        with open(os.path.join(wallet.WALLET_DIR, "prueba", "apple", "pass.pem")) as f:
            otra_ca = f.read()                                                                                   # no es la CA que firmó
        self.assertFalse(wallet_apple.verificar(datos, otra_ca)[0])

    def test_push_simulado_tras_un_sello(self):
        t = sellos.crear_tarjeta()["id"]
        sellos.registrar_dispositivo("movil-1", "push-token-1", t)
        wallet.REGISTRO.clear()
        sellos.sellar(t, 6, "servido", pedido_id="e1")
        wallet.notificar(t)
        apns = [x for x in wallet.REGISTRO if x["canal"] == "apns"]
        self.assertEqual(apns, [{"canal": "apns", "push_token": "push-token-1", "topic": wallet_apple.identificadores()[0]}])


@unittest.skipUnless(HAY_OPENSSL, "hace falta openssl")
class WalletGoogle(unittest.TestCase):
    def test_enlace_de_guardado_firmado(self):
        t = sellos.crear_tarjeta()["id"]
        url = wallet_google.enlace_guardar(t, "https://carta.ejemplo.es")
        self.assertTrue(url.startswith("https://pay.google.com/gp/v/save/"))
        jwt = url.rsplit("/", 1)[1]
        self.assertTrue(wallet_google.verificar_jwt(jwt, wallet_google.clave_publica()))
        cuerpo = jwt.split(".")[1]
        c = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
        self.assertEqual((c["aud"], c["typ"], c["origins"]), ("google", "savetowallet", ["https://carta.ejemplo.es"]))
        obj = c["payload"]["loyaltyObjects"][0]
        self.assertEqual((obj["barcode"]["value"], obj["classId"]), (t, c["payload"]["loyaltyClasses"][0]["id"]))
        self.assertTrue(obj["id"].endswith("." + t))
        # un JWT retocado no verifica
        cab, _, firma = jwt.split(".")
        falso = base64.urlsafe_b64encode(json.dumps({**c, "iss": "otro@x"}).encode()).rstrip(b"=").decode()
        self.assertFalse(wallet_google.verificar_jwt(f"{cab}.{falso}.{firma}", wallet_google.clave_publica()))
        self.assertIsNone(wallet_google.enlace_guardar("no-existe-123456", "https://x"))

    def test_objeto_se_actualiza_tras_un_sello(self):
        t = sellos.crear_tarjeta()["id"]
        wallet.REGISTRO.clear()
        sellos.sellar(t, 6, "servido", pedido_id="g1")
        wallet.notificar(t)
        g = [x for x in wallet.REGISTRO if x["canal"] == "google"]
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["objeto"], wallet_google.ids(t)[1])
        self.assertEqual(g[0]["cuerpo"]["loyaltyPoints"]["balance"]["string"], "1 / 3")


@unittest.skipUnless(HAY_OPENSSL, "hace falta openssl")
class Idiomas(unittest.TestCase):
    """La tarjeta (página, pase de Apple, objeto de Google y errores) sale en el idioma de la tarjeta."""
    ESTADO = {"es": "Te faltan 3 para el premio", "en": "3 to go for your reward", "ca": "Et falten 3 per al premi", "zh": "距离领奖还差 3 个",
              "fr": "Il vous en manque 3 pour la récompense", "de": "Es fehlen noch 3 bis zur Prämie", "it": "Te ne mancano 3 per il premio",
              "pt": "Faltam-te 3 para o prémio"}

    def setUp(self):
        sellos.guardar_config({"activo": True, "sellos_meta": 3, "premio": "Un plato gratis", "importe_minimo": 5})

    def test_la_tarjeta_se_genera_en_su_idioma(self):
        for idioma in idiomas.IDIOMAS:
            t = sellos.crear_tarjeta(idioma)["id"]
            self.assertEqual(sellos.estado(t)["idioma"], idioma)
            pj = json.loads(zipfile.ZipFile(io.BytesIO(wallet_apple.construir(t, "https://x.es"))).read("pass.json"))
            self.assertEqual(pj["storeCard"]["secondaryFields"][0]["value"], self.ESTADO[idioma])
            self.assertNotIn("{", pj["storeCard"]["backFields"][0]["value"])
            g = wallet_google.objeto(sellos.estado(t), sellos.restaurante.marca(), idioma)
            self.assertEqual(g["secondaryLoyaltyPoints"]["label"], idiomas.t("wallet.google.estado", idioma))
            pagina = tarjeta_web.pagina(idioma).decode()
            self.assertIn(f'<html lang="{idioma}">', pagina)
            self.assertIn(idiomas.t("tarjeta.pagina.pie", idioma), pagina)
        # el pedido a mano manda sobre el de la tarjeta, y un idioma raro cae a castellano
        t = sellos.crear_tarjeta("en")["id"]
        pj = json.loads(zipfile.ZipFile(io.BytesIO(wallet_apple.construir(t, "https://x.es", "ca"))).read("pass.json"))
        self.assertEqual(pj["storeCard"]["secondaryFields"][0]["value"], self.ESTADO["ca"])
        self.assertEqual(sellos.estado(sellos.crear_tarjeta("nl")["id"])["idioma"], "es")

    def test_el_premio_sale_en_el_idioma_de_la_tarjeta(self):
        """El premio no se queda en castellano en las tarjetas en otros idiomas."""
        sellos.guardar_config({"activo": True, "sellos_meta": 3, "premio": "Un plato gratis", "importe_minimo": 5,
                               "premio_i18n": {"en": "A free dish", "zh": "  ", "ca": ""}})
        self.assertEqual(sellos.config()["premio_i18n"], {"en": "A free dish"})
        for idioma, esperado in (("es", "Un plato gratis"), ("en", "A free dish"), ("ca", "Un plato gratis"), ("zh", "Un plato gratis")):
            t = sellos.crear_tarjeta(idioma)["id"]
            self.assertEqual(sellos.estado(t)["premio"], esperado)
            pj = json.loads(zipfile.ZipFile(io.BytesIO(wallet_apple.construir(t, "https://x.es"))).read("pass.json"))
            self.assertEqual(pj["storeCard"]["primaryFields"][0]["value"], esperado)
        t = sellos.crear_tarjeta("es")["id"]
        self.assertEqual(sellos.estado(t, "en")["premio"], "A free dish")   # el idioma de quien pregunta manda sobre el de la tarjeta
        self.assertEqual(sellos.premios(sellos.config())["en"], "A free dish")

    def test_el_premio_de_fabrica_viene_traducido(self):
        sellos.guardar_config({"activo": True, "sellos_meta": 3, "premio": sellos.POR_DEFECTO["premio"], "importe_minimo": 5})
        vistos = {sellos.premio_en(sellos.config(), i) for i in idiomas.IDIOMAS}
        self.assertEqual(len(vistos), len(idiomas.IDIOMAS), vistos)   # un texto distinto por idioma: ninguno es el castellano pegado
        self.assertEqual(sellos.premio_en(sellos.config(), "es"), "Un detalle de la casa")
        sellos.guardar_config({"activo": True, "sellos_meta": 3, "premio": "Café gratis", "importe_minimo": 5})
        self.assertEqual({sellos.premio_en(sellos.config(), i) for i in idiomas.IDIOMAS}, {"Café gratis"})   # un premio propio sin traducir no inventa nada

    def test_premio_traducido_validado(self):
        base = {"activo": True, "sellos_meta": 3, "premio": "x", "importe_minimo": 1}
        for malo in ({"en": "y" * 81}, {"en": 5}, {"zh": "a\nb"}, "texto"):
            with self.assertRaises(ValueError, msg=repr(malo)):
                sellos.guardar_config({**base, "premio_i18n": malo})

    def test_cambiar_el_idioma_toca_la_tarjeta_solo_si_cambia(self):
        t = sellos.crear_tarjeta("es")["id"]
        antes = sellos.estado(t)["actualizado"]
        sellos.poner_idioma(t, "es")
        self.assertEqual(sellos.estado(t)["actualizado"], antes)
        sellos.poner_idioma(t, "zh")
        e = sellos.estado(t)
        self.assertEqual(e["idioma"], "zh")
        self.assertGreater(e["actualizado"], antes)      # Apple volverá a pedir el pase

    def test_errores_de_ajustes_traducibles(self):
        with self.assertRaises(ValueError) as c:
            sellos.validar_config({"activo": True, "sellos_meta": 0, "premio": "x", "importe_minimo": 1})
        self.assertIn("1 a 30", str(c.exception))
        self.assertIn("1 to 30", idiomas.mensaje(c.exception, "en"))
        self.assertIn("1 a 30", idiomas.mensaje(c.exception, "ca"))


class SinCredenciales(unittest.TestCase):
    def test_sin_modo_prueba_ni_credenciales_el_canal_no_esta(self):
        os.environ.pop("WALLET_MODO")
        try:
            self.assertIsNone(wallet_apple.modo())
            self.assertIsNone(wallet_google.modo())
            with self.assertRaises(RuntimeError):
                wallet_apple.credenciales()
            wallet_apple.empujar("no-existe-123456")      # no hace nada ni falla
            wallet_google.actualizar("no-existe-123456")
        finally:
            os.environ["WALLET_MODO"] = "prueba"


if __name__ == "__main__":
    unittest.main(verbosity=2)
