# SPDX-License-Identifier: EUPL-1.2
"""Pruebas de la plantilla de restaurante:  python -m unittest discover -s tests -v   (desde la raíz del repo)

Crean restaurantes en carpetas temporales (CARTA_RESTAURANTES / CARTA_WEB): no tocan restaurantes/ ni carta/web/."""
import json, os, re, socket, subprocess, sys, tempfile, time, unittest, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTA = os.path.join(RAIZ, "carta")
sys.path.insert(0, CARTA)
import nuevo_restaurante  # noqa: E402

try:
    import PIL  # noqa: F401
    HAY_PIL = True
except ImportError:
    HAY_PIL = False


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def entorno(slug, raiz, web):
    return {**os.environ, "RESTAURANTE": slug, "CARTA_RESTAURANTES": raiz, "CARTA_WEB": web}


class Servidor:
    """Prepara web/ y arranca servidor.py para un restaurante, en carpetas temporales."""

    def __init__(self, slug, raiz):
        self.web = tempfile.mkdtemp(prefix="web-")
        self.env = entorno(slug, raiz, self.web)
        subprocess.run([sys.executable, "preparar_netlify.py"], cwd=CARTA, env=self.env, check=True, capture_output=True)
        self.puerto = puerto_libre()
        self.proc = subprocess.Popen([sys.executable, "servidor.py", "--puerto", str(self.puerto)], cwd=CARTA, env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                self.get("/api/sesion")
                return
            except OSError:
                time.sleep(0.1)
        self.parar()
        raise RuntimeError("el servidor no arrancó")

    def get(self, ruta):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.puerto}{ruta}", timeout=10) as r:
            return r.read()

    def texto(self, ruta):
        return self.get(ruta).decode("utf-8")

    def parar(self):
        self.proc.terminate()
        self.proc.wait(10)


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


class NuevoRestaurante(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_crea_la_estructura(self):
        c = nuevo_restaurante.crear("demo", "Demo Bar", raiz=self.raiz)
        for f in ("marca.json", "datos.json", "datos.js", "fotos.json", "fotos.js", "marca/logo_provisional.png"):
            self.assertTrue(os.path.isfile(os.path.join(c, f)), f)
        self.assertTrue(os.path.isdir(os.path.join(c, "fotos")))
        m = json.loads(leer(os.path.join(c, "marca.json")))
        self.assertEqual((m["nombre"], m["nombre_resalte"]), ("Demo Bar", "Bar"))
        with open(os.path.join(c, "marca", "logo_provisional.png"), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_nombre_por_defecto_sale_del_slug(self):
        c = nuevo_restaurante.crear("bar-pepe", raiz=self.raiz)
        self.assertEqual(json.loads(leer(os.path.join(c, "marca.json")))["nombre"], "Bar Pepe")

    def test_slug_no_valido(self):
        for malo in ("", "Demo", "../x", "a/b", "-x", "con espacio"):
            with self.assertRaises(ValueError, msg=malo):
                nuevo_restaurante.crear(malo, raiz=self.raiz)
        self.assertEqual(os.listdir(self.raiz), [])

    def test_color_no_valido(self):
        with self.assertRaises(ValueError):
            nuevo_restaurante.crear("demo", color="rojo", raiz=self.raiz)

    def test_no_pisa_un_restaurante_existente(self):
        c = nuevo_restaurante.crear("demo", raiz=self.raiz)
        marca = os.path.join(c, "marca.json")
        with open(marca, "a", encoding="utf-8") as f:
            f.write("\n")
        antes = leer(marca)
        with self.assertRaises(ValueError):
            nuevo_restaurante.crear("demo", "Otro", raiz=self.raiz)
        self.assertEqual(leer(marca), antes)

    def test_script_por_linea_de_comandos(self):
        env = {**os.environ, "CARTA_RESTAURANTES": self.raiz}
        ok = subprocess.run([sys.executable, "nuevo_restaurante.py", "demo"], cwd=CARTA, env=env, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        repetido = subprocess.run([sys.executable, "nuevo_restaurante.py", "demo"], cwd=CARTA, env=env, capture_output=True, text=True)
        self.assertNotEqual(repetido.returncode, 0)
        self.assertIn("Ya existe", repetido.stderr)


class Marca(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ.setdefault("RESTAURANTE", "demo")
        import restaurante
        self.restaurante = restaurante

    def tearDown(self):
        self.tmp.cleanup()

    def carpeta(self, marca):
        with open(os.path.join(self.tmp.name, "marca.json"), "w", encoding="utf-8") as f:
            json.dump(marca, f)
        return self.tmp.name

    def test_marca_minima_se_completa(self):
        m = self.restaurante.cargar_marca(self.carpeta({"nombre": "Bar Pepe", "logo": "l.png"}))
        self.assertEqual((m["nombre_corto"], m["nombre_resalte"]), ("Bar Pepe", "Pepe"))
        self.assertEqual(m["colores"]["acento"], self.restaurante.COLORES["acento"])
        self.assertEqual(m["color_fondo"], m["colores"]["fondo"])

    def test_marcas_no_validas(self):
        casos = [{"logo": "l.png"}, {"nombre": "A", "logo": "../l.png"}, {"nombre": "A`B", "logo": "l.png"},
                 {"nombre": "A", "logo": "l.png", "intro": "${x}"}, {"nombre": "A", "logo": "l.png", "colores": {"acento": "rojo"}},
                 {"nombre": "Bar Pepe", "logo": "l.png", "nombre_resalte": "Juan"}]
        for caso in casos:
            with self.assertRaises(ValueError, msg=caso):
                self.restaurante.cargar_marca(self.carpeta(caso))

    def test_plantilla_escapa_y_rechaza_marcadores_desconocidos(self):
        r = self.restaurante
        antes = r.marca
        r.marca = lambda: r.cargar_marca(self.carpeta({"nombre": "Bar <Pepe> & Co", "logo": "l.png"}))
        try:
            self.assertEqual(r.plantilla("<b>{{nombre}}</b>"), "<b>Bar &lt;Pepe&gt; &amp; Co</b>")
            self.assertEqual(r.plantilla("{{js:nombre}}"), '"Bar \\u003cPepe> & Co"')
            with self.assertRaises(KeyError):
                r.plantilla("{{no_existe}}")
        finally:
            r.marca = antes


@unittest.skipUnless(HAY_PIL, "hace falta Pillow (el mismo que usa preparar_netlify.py)")
class ArrancaConSuMarca(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        nuevo_restaurante.crear("demo", "Bar Demo", "#2A6F4F", raiz=cls.tmp.name)
        cls.demo = Servidor("demo", cls.tmp.name)
        cls.demo_repo = Servidor("demo", os.path.join(RAIZ, "restaurantes"))

    @classmethod
    def tearDownClass(cls):
        cls.demo.parar()
        cls.demo_repo.parar()
        cls.tmp.cleanup()

    def test_las_tres_paginas_llevan_la_marca_de_demo(self):
        for ruta in ("/", "/admin", "/cocina"):
            t = self.demo.texto(ruta)
            self.assertIn("Bar Demo", t.replace('<b class="r">Bar </b><span>Demo</span>', "Bar Demo"), ruta)
            self.assertNotIn("googleapis", t, ruta)
            self.assertIn("logo_provisional.png", t, ruta)
            self.assertIsNone(re.search(r"\{\{", t), ruta)
            self.assertIn("tema.css", t, ruta)

    def test_manifiesto_logo_y_datos_de_demo(self):
        man = json.loads(self.demo.get("/manifest.webmanifest"))
        self.assertEqual((man["name"], man["short_name"]), ("Bar Demo · Carta", "Bar Demo"))
        self.assertEqual(self.demo.get("/img/logo_provisional.png")[:4], b"\x89PNG")
        self.assertIn("Plato de ejemplo", self.demo.texto("/datos.js"))

    def test_datos_de_demo_pasan_la_validacion_del_servidor(self):
        env = entorno("demo", self.tmp.name, self.demo.web)
        código = ("import json, servidor; d = json.load(open(servidor.DATOS, encoding='utf-8')); "
                  "assert servidor.validar(d)['platos'][0]['n'] == 'Plato de ejemplo'")
        r = subprocess.run([sys.executable, "-c", código], cwd=CARTA, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_la_demo_del_repo_lleva_su_marca_y_su_tema(self):
        marca = json.load(open(os.path.join(RAIZ, "restaurantes", "demo", "marca.json"), encoding="utf-8"))
        t = self.demo_repo.texto("/")
        self.assertIn(f"<title>{marca['nombre']}</title>", t)
        self.assertIn(f'<b class="r">{marca["nombre"][:-len(marca["nombre_resalte"])]}</b><span>{marca["nombre_resalte"]}</span>', t)
        self.assertIn(f'src="img/{marca["logo"]}"', t)
        self.assertIn('href="tema.css"', t)
        self.assertIn(f"--acento:{marca['colores']['acento']}", self.demo_repo.texto("/tema.css"))
        self.assertIn("'demo_mesa'", t)
        self.assertIn(marca["lema"]["es"], t)
        cocina = self.demo_repo.texto("/cocina")
        self.assertIn("<span>Tu Restaurante</span>", cocina)
        self.assertIn('data-i18n="cocina.nombre"', cocina)
        self.assertEqual(json.loads(self.demo_repo.get("/manifest.webmanifest"))["name"], f"{marca['nombre']} · Carta")
        self.assertIn("carta.chips.tu_plato", t)
        for ruta in ("/", "/admin", "/cocina"):
            self.assertNotIn("googleapis", self.demo_repo.texto(ruta), ruta)
            self.assertIsNone(re.search(r"\{\{", self.demo_repo.texto(ruta)), ruta)

    def test_el_vocabulario_y_la_tipografia_vienen_de_la_marca(self):
        import restaurante
        m = restaurante.cargar_marca(os.path.join(RAIZ, "restaurantes", "demo"))
        self.assertEqual((m["textos"]["plato"]["es"], m["tipografia"]["texto"]), ("plato", restaurante.TIPOGRAFIA["texto"]))
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "marca.json"), "w", encoding="utf-8") as f:
                json.dump({"nombre": "Bar Pepe", "logo": "l.png", "textos": {"plato": "tosta", "platos": "tostas"},
                           "tipografia": {"titulos": "Georgia, serif"}}, f)
            m = restaurante.cargar_marca(tmp)
        self.assertEqual((m["textos"]["plato"], m["tipografia"]["titulos"]), ("tosta", "Georgia, serif"))
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "marca.json"), "w", encoding="utf-8") as f:
                json.dump({"nombre": "Bar Pepe", "logo": "l.png", "tipografia": {"texto": "a;}</style>"}}, f)
            with self.assertRaises(ValueError):
                restaurante.cargar_marca(tmp)


if __name__ == "__main__":
    unittest.main()
