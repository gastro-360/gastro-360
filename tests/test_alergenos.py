# SPDX-License-Identifier: EUPL-1.2
"""Alérgenos (Reglamento UE 1169/2011, anexo II):  python -m unittest tests.test_alergenos -v   (desde la raíz del repo)"""
import json, os, re, sys, tempfile, unittest, urllib.error, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTA = os.path.join(RAIZ, "carta")
sys.path.insert(0, CARTA)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
os.environ.setdefault("RESTAURANTE", "demo")
import alergenos  # noqa: E402
import nuevo_restaurante  # noqa: E402
from test_plantilla import HAY_PIL, Servidor  # noqa: E402

LOS_14 = {"gluten", "crustaceans", "eggs", "fish", "peanuts", "soybeans", "milk", "tree_nuts", "celery", "mustard",
          "sesame", "sulphites", "lupin", "molluscs"}


class Modulo(unittest.TestCase):
    def test_son_exactamente_los_14(self):
        self.assertEqual(len(alergenos.LISTA), 14)
        self.assertEqual(set(alergenos.LISTA), LOS_14)

    def test_cada_uno_tiene_nombre_en_castellano_e_icono_sin_texto(self):
        for i in alergenos.LISTA:
            self.assertTrue(alergenos.nombre(i, "es"), i)
            svg = alergenos.icono(i)
            self.assertTrue(svg.lstrip().startswith("<svg"), i)
            self.assertNotIn("<text", svg, "el icono nunca lleva la etiqueta dentro: va aparte, en HTML")
            self.assertNotIn("http", svg.replace("http://www.w3.org/2000/svg", ""), i)

    def test_limpiar(self):
        self.assertIsNone(alergenos.limpiar(None, "x"))
        self.assertEqual(alergenos.limpiar([], "x"), [])
        self.assertEqual(alergenos.limpiar(["milk", "gluten", "milk"], "x"), ["gluten", "milk"])
        for malo in ("gluten", {"gluten": 1}, ["gluten", "lactosa"], ["GLUTEN"], [1], [["milk"]], 3):
            with self.assertRaises(ValueError, msg=malo):
                alergenos.limpiar(malo, "Plato")

    def test_tres_estados_distintos(self):
        est = {alergenos.estado(["gluten"]), alergenos.estado([]), alergenos.estado(None)}
        self.assertEqual(est, {alergenos.MARCADOS, alergenos.SIN_DECLARAR, alergenos.SIN_REVISAR})

    def test_aviso_fijo(self):
        self.assertEqual(alergenos.AVISO, "Información facilitada por el restaurante; consulta al personal")

    def test_publicos(self):
        p = alergenos.publicos()
        self.assertEqual({x["id"] for x in p["lista"]}, LOS_14)
        self.assertTrue(all(x["n"] and x["svg"] for x in p["lista"]))


class Validacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import servidor
        cls.s = servidor

    def datos(self, **plato):
        d = json.load(open(os.path.join(RAIZ, "restaurantes", "demo", "datos.json"), encoding="utf-8"))
        d["platos"][0].pop("alergenos", None)
        d["platos"][0].update(plato)
        return d

    def test_conserva_los_tres_estados(self):
        self.assertEqual(self.s.validar(self.datos(alergenos=["milk", "gluten"]))["platos"][0]["alergenos"], ["gluten", "milk"])
        self.assertEqual(self.s.validar(self.datos(alergenos=[]))["platos"][0]["alergenos"], [])
        self.assertNotIn("alergenos", self.s.validar(self.datos())["platos"][0])

    def test_rechaza_fuera_de_los_14(self):
        with self.assertRaises(ValueError):
            self.s.validar(self.datos(alergenos=["gluten", "pescado"]))

    def test_la_demo_muestra_los_tres_estados(self):
        d = self.s.validar(json.load(open(os.path.join(RAIZ, "restaurantes", "demo", "datos.json"), encoding="utf-8")))
        vistos = set()
        for p in d["platos"] + d.get("picar", []):
            vistos.add(alergenos.estado(p.get("alergenos")))
        self.assertEqual(vistos, {alergenos.MARCADOS, alergenos.SIN_DECLARAR, alergenos.SIN_REVISAR})


@unittest.skipUnless(HAY_PIL, "hace falta Pillow")
class Servido(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        nuevo_restaurante.crear("bar", "Bar Prueba", raiz=cls.tmp.name)
        ruta = os.path.join(cls.tmp.name, "bar", "marca.json")
        m = json.load(open(ruta, encoding="utf-8"))
        m["aviso_alergenos"] = "Aviso inventado por el dueño"
        json.dump(m, open(ruta, "w", encoding="utf-8"))
        os.environ["CLAVE_BACKOFFICE"] = "clave-de-prueba"
        cls.srv = Servidor("bar", cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.srv.parar()
        os.environ.pop("CLAVE_BACKOFFICE", None)
        cls.tmp.cleanup()

    def peticion(self, metodo, ruta, cuerpo=None, cookie=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.puerto}{ruta}", method=metodo,
                                     data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                     headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def entrar(self):
        _, _, h = self.peticion("POST", "/api/login", {"clave": "clave-de-prueba"})
        return h["Set-Cookie"].split(";")[0]

    def test_aviso_fijo_en_la_carta_y_no_se_puede_cambiar(self):
        t = self.srv.texto("/")
        self.assertGreaterEqual(t.count(alergenos.AVISO), 3, "carta, tarjeta Pedido y diálogo de envío")
        self.assertNotIn("Aviso inventado", t)
        self.assertIsNone(re.search(r"\{\{", t))

    def test_alergenos_js_lleva_los_14(self):
        js = self.srv.texto("/alergenos.js")
        for i in LOS_14:
            self.assertIn(f'"{i}"', js)
        self.assertIn(alergenos.texto("sin_declarar"), js)
        self.assertIn(alergenos.texto("sin_revisar"), js)

    def test_guardar_y_rechazar(self):
        c = self.entrar()
        st, cuerpo, _ = self.peticion("GET", "/api/datos", cookie=c)
        d = json.loads(cuerpo)
        self.assertTrue(d["platos"])
        d["platos"][0]["alergenos"] = ["eggs", "sesame"]
        malo = json.loads(json.dumps(d))
        malo["platos"][0]["alergenos"] = ["eggs", "kiwi"]
        st, cuerpo, _ = self.peticion("PUT", "/api/datos", malo, c)
        self.assertEqual(st, 400)
        self.assertIn("14 alérgenos", json.loads(cuerpo)["error"])
        st, _, _ = self.peticion("PUT", "/api/datos", d, c)
        self.assertEqual(st, 200)
        d2 = json.loads(self.peticion("GET", "/api/datos", cookie=c)[1])
        self.assertEqual(d2["platos"][0]["alergenos"], ["eggs", "sesame"])
        d2["platos"][0]["alergenos"] = []
        self.assertEqual(self.peticion("PUT", "/api/datos", d2, c)[0], 200)
        d3 = json.loads(self.peticion("GET", "/api/datos", cookie=c)[1])
        self.assertEqual(d3["platos"][0]["alergenos"], [])
        del d3["platos"][0]["alergenos"]
        self.assertEqual(self.peticion("PUT", "/api/datos", d3, c)[0], 200)
        self.assertNotIn("alergenos", json.loads(self.peticion("GET", "/api/datos", cookie=c)[1])["platos"][0])


if __name__ == "__main__":
    unittest.main()
