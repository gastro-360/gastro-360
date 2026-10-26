# SPDX-License-Identifier: EUPL-1.2
"""Pruebas del módulo de clientes y permisos (SQLite):  python -m unittest tests.test_clientes   (desde la raíz del repo)
Usan una carpeta temporal (CARTA_RESTAURANTES): no tocan restaurantes/."""
import contextlib, os, shutil, sqlite3, sys, tempfile, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="clientes-")
os.environ["CARTA_RESTAURANTES"] = TMP
os.environ["RESTAURANTE"] = "demo"
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import clientes, idiomas  # noqa: E402


def alta_confirmada(email, **kw):
    """Alta como la deja el doble opt-in: solicitud pendiente + clic del titular en el enlace del correo. Devuelve el id del cliente."""
    con = sqlite3.connect(clientes.DB)       # lo anterior de esa dirección queda fuera de la hora de espera
    con.execute("update solicitudes set creada='2000-01-01T00:00:00+00:00' where cliente_id in (select id from clientes where email=?)", (email,))
    con.commit(); con.close()
    cid, token = clientes.solicitar_alta(email, **kw)
    if token:
        assert clientes.confirmar(token)
    return cid


@contextlib.contextmanager
def con_doble(valor):
    """Fija CONFIRMACION_DOBLE durante el bloque («1» = doble confirmación, «» = alta directa, el valor por defecto)."""
    antes = os.environ.get("CONFIRMACION_DOBLE")
    os.environ["CONFIRMACION_DOBLE"] = valor
    try:
        yield
    finally:
        if antes is None:
            os.environ.pop("CONFIRMACION_DOBLE", None)
        else:
            os.environ["CONFIRMACION_DOBLE"] = antes


class Clientes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(os.path.dirname(clientes.DB), exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def token(self, email):
        return sqlite3.connect(clientes.DB).execute("select token_baja from clientes where email=?", (email,)).fetchone()[0]

    def test_ciclo_completo(self):
        email = clientes.validar_permiso({"email": " Ana@Ejemplo.COM ", "version": clientes.TEXTO_VERSION})
        self.assertEqual(email, "ana@ejemplo.com")
        self.assertFalse(clientes.apto_marketing(email))   # nadie es apto sin alta
        cid = alta_confirmada(email)
        self.assertTrue(clientes.apto_marketing(email))
        f = clientes.ficha(cid)
        self.assertEqual(f["permisos"][0]["texto"], clientes.texto_permiso())
        self.assertEqual(f["permisos"][0]["texto_version"], clientes.TEXTO_VERSION)
        self.assertIn("Bar Demo", f["permisos"][0]["texto"])
        self.assertTrue(clientes.registrar_baja(self.token(email)))
        self.assertFalse(clientes.apto_marketing(email))
        self.assertEqual([p["accion"] for p in clientes.ficha(cid)["permisos"]], ["alta", "baja"])
        # nueva alta tras la baja: mismo cliente, mismo token, vuelve a ser apto con una prueba nueva
        self.assertEqual(alta_confirmada(email), cid)
        self.assertTrue(clientes.apto_marketing(email))
        self.assertEqual([p["accion"] for p in clientes.ficha(cid)["permisos"]], ["alta", "baja", "alta"])

    def test_validaciones(self):
        for malo in ("", "sin-arroba", "a@b", "a b@c.es", "{{x}}@c.es", "<a>@c.es", None, 5):
            with self.assertRaises(ValueError, msg=repr(malo)):
                clientes.validar_email(malo)
        with self.assertRaises(ValueError):
            clientes.validar_permiso({"email": "a@b.es", "version": "0"})
        with self.assertRaises(ValueError):
            clientes.validar_permiso("a@b.es")
        self.assertFalse(clientes.registrar_baja("no-existe-" + "x" * 20))
        self.assertFalse(clientes.registrar_baja(None))

    def test_idioma_del_cliente_y_prueba_del_permiso(self):
        for idioma in idiomas.IDIOMAS:
            email = f"idioma-{idioma}@ejemplo.com"
            cid = alta_confirmada(email, idioma=idioma)
            f = clientes.ficha(cid)
            self.assertEqual(f["idioma"], idioma)
            p = f["permisos"][0]
            self.assertEqual(p["idioma"], idioma)
            self.assertEqual(p["texto"], clientes.texto_permiso(idioma))     # la prueba guarda el texto exacto que vio
            self.assertEqual(p["texto_version"], clientes.TEXTO_VERSION)
            self.assertIn("Bar Demo", p["texto"])
            self.assertEqual([d["idioma"] for d in clientes.destinatarios("email") if d["email"] == email], [idioma])
        self.assertEqual(len({clientes.texto_permiso(i) for i in idiomas.IDIOMAS}), len(idiomas.IDIOMAS))
        self.assertEqual(clientes.ficha("idioma-es@ejemplo.com")["idioma"], "es")
        cid = alta_confirmada("sin-idioma@ejemplo.com")
        self.assertEqual(clientes.ficha(cid)["permisos"][0]["idioma"], "es")

    def test_errores_traducibles(self):
        with self.assertRaises(ValueError) as c:
            clientes.validar_email("mal")
        self.assertIn("correo electrónico", str(c.exception))
        self.assertIn("email", idiomas.mensaje(c.exception, "en"))
        self.assertNotEqual(idiomas.mensaje(c.exception, "zh"), str(c.exception))

    def test_pagina_de_baja_en_cada_idioma(self):
        cid = alta_confirmada("baja-ca@ejemplo.com", idioma="ca")
        tok = self.token("baja-ca@ejemplo.com")
        for lang, trozo in (("es", "Darme de baja"), ("en", "Unsubscribe"), ("ca", "Donar-me de baixa"), ("zh", "退订")):
            h = clientes.pagina_baja(tok, lang=lang).decode()
            self.assertIn(f'<html lang="{lang}">', h)
            self.assertIn(trozo, h)
            self.assertIn("baja-ca@ejemplo.com", h)
        self.assertIn('<html lang="ca">', clientes.pagina_baja(tok).decode())       # sin ?lang=: el idioma guardado del cliente
        self.assertIn('<html lang="en">', clientes.pagina_baja("x" * 24, {"X-Idioma": "en"}).decode())   # enlace roto: el de la petición
        self.assertEqual(clientes.enlace_baja(tok, "https://x.es/", "zh"), f"https://x.es/baja?t={tok}&lang=zh")

    def test_doble_optin_solo_el_clic_del_titular_da_el_alta(self):
        email = "doble-optin@ejemplo.com"
        cid, token = clientes.solicitar_alta(email, idioma="en")
        self.assertTrue(token)
        self.assertFalse(clientes.apto_marketing(email))
        self.assertNotIn(email, [d["email"] for d in clientes.destinatarios("email")])
        f = clientes.ficha(cid)
        self.assertEqual((f["permisos"], f["apto_marketing"]), ([], False))
        self.assertTrue(f["pendiente"])
        pend = [c for c in clientes.listar() if c["id"] == cid]         # el dueño lo ve como pendiente, nunca como apto
        self.assertEqual([(c["pendiente"] is not None, c["apto_marketing"], c["permisos"]) for c in pend], [(True, False, [])])
        with con_doble("1"):
            self.assertEqual(clientes.registrar_alta(email), cid)       # lo que hace el pedido con CONFIRMACION_DOBLE=1: tampoco da el alta
        self.assertFalse(clientes.apto_marketing(email))
        self.assertIn("doble-optin@ejemplo.com", clientes.pagina_confirmar(token, lang="en").decode())
        self.assertFalse(clientes.confirmar("x" * 24))                 # token inventado
        self.assertTrue(clientes.confirmar(token))
        self.assertTrue(clientes.apto_marketing(email))
        p = clientes.ficha(cid)["permisos"][0]
        self.assertEqual((p["accion"], p["texto_version"], p["idioma"]), ("alta", clientes.TEXTO_VERSION, "en"))
        self.assertEqual(p["texto"], clientes.texto_permiso("en"))
        self.assertIn("pedido-carta", p["canal"])
        self.assertTrue(p["fecha"])
        self.assertFalse(clientes.confirmar(token))                    # un solo uso
        self.assertIsNone(clientes.ficha(cid)["pendiente"])

    def test_alta_directa_por_defecto(self):
        """Sin CONFIRMACION_DOBLE, marcar la casilla da el alta con la prueba completa, sin solicitud ni token, y no duplica."""
        with con_doble(""):
            self.assertFalse(clientes.confirmacion_doble())
            email = "directo@ejemplo.com"
            cid = clientes.registrar_alta(email, idioma="en")
            self.assertTrue(clientes.apto_marketing(email))
            self.assertIn(email, [d["email"] for d in clientes.destinatarios("email")])
            f = clientes.ficha(cid)
            self.assertIsNone(f["pendiente"])
            self.assertEqual(len(f["permisos"]), 1)
            p = f["permisos"][0]
            self.assertEqual((p["accion"], p["canal"], p["texto_version"], p["idioma"]), ("alta", clientes.CANAL_PEDIDO, clientes.TEXTO_VERSION, "en"))
            self.assertEqual(p["texto"], clientes.texto_permiso("en"))
            self.assertRegex(p["fecha"], r"^\d{4}-\d\d-\d\dT")
            self.assertEqual(clientes.registrar_alta(email), cid)       # ya es apto: no duplica
            self.assertEqual(len(clientes.ficha(cid)["permisos"]), 1)
            with clientes.conectar() as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM solicitudes WHERE cliente_id=?", (cid,)).fetchone()[0], 0)
            clientes.registrar_baja(self.token(email))                  # tras la baja, volver a marcar la casilla es un alta nueva
            self.assertFalse(clientes.apto_marketing(email))
            clientes.registrar_alta(email)
            self.assertEqual([x["accion"] for x in clientes.ficha(cid)["permisos"]], ["alta", "baja", "alta"])

    def test_confirmacion_doble_solo_con_la_variable(self):
        for valor, esperado in (("", False), ("0", False), ("1", True)):
            with con_doble(valor):
                self.assertEqual(clientes.confirmacion_doble(), esperado)

    def test_un_correo_por_hora_y_direccion(self):
        email = "limite-hora@ejemplo.com"
        cid, token = clientes.solicitar_alta(email)
        self.assertTrue(token)
        self.assertEqual(clientes.solicitar_alta(email), (cid, None))
        con = sqlite3.connect(clientes.DB)       # pasa más de una hora
        antes = (clientes.datetime.datetime.now().astimezone() - clientes.datetime.timedelta(hours=1, minutes=1)).isoformat(timespec="seconds")
        con.execute("update solicitudes set creada=? where cliente_id=?", (antes, cid))
        con.commit(); con.close()
        self.assertTrue(clientes.solicitar_alta(email)[1])
        alta_confirmada("yaconpermiso2@ejemplo.com")
        self.assertIsNone(clientes.solicitar_alta("yaconpermiso2@ejemplo.com")[1])   # ya tiene permiso: no se le escribe

    def test_el_token_caduca_a_los_7_dias(self):
        cid, token = clientes.solicitar_alta("caduca@ejemplo.com")
        con = sqlite3.connect(clientes.DB)
        viejo = (clientes.datetime.datetime.now().astimezone() - clientes.CADUCIDAD - clientes.datetime.timedelta(minutes=1)).isoformat(timespec="seconds")
        con.execute("update solicitudes set creada=? where cliente_id=?", (viejo, cid))
        con.commit(); con.close()
        self.assertFalse(clientes.confirmar(token))
        self.assertFalse(clientes.apto_marketing("caduca@ejemplo.com"))
        self.assertIn("no es válido", clientes.pagina_confirmar(token, lang="es").decode())

    def test_una_baja_invalida_lo_pendiente(self):
        cid, token = clientes.solicitar_alta("baja-pendiente@ejemplo.com")
        self.assertTrue(clientes.registrar_baja(self.token("baja-pendiente@ejemplo.com")))
        self.assertFalse(clientes.confirmar(token))
        self.assertFalse(clientes.apto_marketing("baja-pendiente@ejemplo.com"))

    def test_pagina_de_confirmar_en_cada_idioma_y_enlace(self):
        cid, token = clientes.solicitar_alta("conf-ca@ejemplo.com", idioma="ca")
        for lang, trozo in (("es", "Confirmar las promociones"), ("en", "Confirm promotions"), ("ca", "Confirmar les promocions"), ("zh", "确认促销信息")):
            h = clientes.pagina_confirmar(token, lang=lang).decode()
            self.assertIn(f'<html lang="{lang}">', h)
            self.assertIn(trozo, h)
            self.assertIn("/api/confirmar", h)
        self.assertIn('<html lang="ca">', clientes.pagina_confirmar(token).decode())
        self.assertIn("hidden", clientes.pagina_confirmar("x" * 24, {"X-Idioma": "en"}).decode())
        self.assertEqual(clientes.enlace_confirmar(token, "https://x.es/", "zh"), f"https://x.es/confirmar?t={token}&lang=zh")

    def test_url_publica_solo_de_la_configuracion(self):
        antes = os.environ.pop("URL_PUBLICA", None)
        try:
            self.assertIsNone(clientes.url_publica())
            os.environ["URL_PUBLICA"] = "https://bar.example/"
            self.assertEqual(clientes.url_publica(), "https://bar.example")
            os.environ["URL_PUBLICA"] = "javascript:alert(1)"
            self.assertIsNone(clientes.url_publica())
        finally:
            os.environ.pop("URL_PUBLICA", None)
            if antes is not None:
                os.environ["URL_PUBLICA"] = antes


if __name__ == "__main__":
    unittest.main(verbosity=2)
