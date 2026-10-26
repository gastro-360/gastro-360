# SPDX-License-Identifier: EUPL-1.2
"""Ocho idiomas (es, en, ca, zh, fr, de, it, pt):  python3 -m unittest tests.test_i18n -v   (desde la raíz del repo)
Diccionarios completos y coherentes, caída a castellano, fechas y números, Accept-Language, datos de la demo y claves que usa el código."""
import datetime, glob, json, os, re, string, sys, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTA = os.path.join(RAIZ, "carta")
sys.path.insert(0, CARTA)
os.environ["RESTAURANTE"] = "demo"
import idiomas  # noqa: E402
import restaurante  # noqa: E402

LENGUAS = idiomas.IDIOMAS
OTROS = tuple(l for l in LENGUAS if l != "es")


def cargar(idioma):
    with open(os.path.join(CARTA, "i18n", idioma + ".json"), encoding="utf-8") as f:
        return json.load(f)


def marcadores(texto):
    """Nombres de los {marcadores} de un texto (los dobles {{ }} son llaves literales)."""
    return {nombre for _, nombre, _, _ in string.Formatter().parse(texto) if nombre}


class Diccionarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = {l: cargar(l) for l in LENGUAS}

    def test_a_mismas_claves_que_el_castellano(self):
        fuente = set(self.d["es"])
        for l in OTROS:
            faltan, sobran = sorted(fuente - set(self.d[l])), sorted(set(self.d[l]) - fuente)
            self.assertFalse(faltan, f"{l}.json: faltan {len(faltan)} claves de es.json: {faltan}")
            self.assertFalse(sobran, f"{l}.json: sobran {len(sobran)} claves que no están en es.json: {sobran}")

    def test_valores_son_texto_no_vacio(self):
        for l in LENGUAS:
            malos = sorted(k for k, v in self.d[l].items() if not isinstance(v, str) or not v.strip())
            self.assertFalse(malos, f"{l}.json: valores vacíos o que no son texto: {malos}")

    def test_b_marcadores_iguales_en_los_cuatro(self):
        for k, v in self.d["es"].items():
            esperados = marcadores(v)
            for l in OTROS:
                if k in self.d[l]:
                    self.assertEqual(esperados, marcadores(self.d[l][k]), f"{k}: los {{marcadores}} de {l} no coinciden con es ({sorted(esperados)})")

    def test_plurales_en_pareja(self):
        for l in LENGUAS:
            for k in self.d[l]:
                if k.endswith(".uno"):
                    self.assertIn(k[:-4] + ".otros", self.d[l], f"{l}: «{k}» sin su plural «.otros»")
                if k.endswith(".otros"):
                    self.assertIn(k[:-6] + ".uno", self.d[l], f"{l}: «{k}» sin su singular «.uno»")

    def test_chino_lleva_chino(self):
        sin = sorted(k for k, v in self.d["zh"].items() if not re.search(r"[一-鿿]", v) and re.search(r"[A-Za-zÁ-ú]{4,}", re.sub(r"\{[^}]*\}", "", v)))
        # Algunas claves son solo nombres propios (Wallet, QR…): se tolera un puñado, no un diccionario sin traducir
        self.assertLess(len(sin), max(10, len(self.d["zh"]) // 20), f"zh.json: demasiadas claves sin caracteres chinos: {sin[:20]}")

    def test_t_con_marcadores_y_caida(self):
        claves = [k for k, v in self.d["es"].items() if marcadores(v)]
        if claves:
            k = claves[0]
            p = {m: "X" for m in marcadores(self.d["es"][k])}
            for l in LENGUAS:
                self.assertNotIn("{", idiomas.t(k, l, **p))
        self.assertEqual(idiomas.t("no.existe.nunca", "zh"), "no.existe.nunca")
        self.assertEqual(idiomas.t("no.existe.nunca"), "no.existe.nunca")


class CamposDeLaCarta(unittest.TestCase):
    def test_c_tr(self):
        self.assertEqual(idiomas.tr("Pan", "zh"), "Pan")                       # texto plano: castellano
        self.assertEqual(idiomas.tr({"es": "Pan", "en": "Bread"}, "en"), "Bread")
        self.assertEqual(idiomas.tr({"es": "Pan", "en": "Bread"}, "ca"), "Pan")  # ausente -> castellano
        self.assertEqual(idiomas.tr({"es": "Pan", "en": ""}, "en"), "Pan")      # vacío -> castellano
        self.assertEqual(idiomas.tr({"es": "Pan", "zh": None}, "zh"), "Pan")
        self.assertEqual(idiomas.tr({"es": "Pan"}, "nl"), "Pan")                # idioma desconocido
        self.assertEqual(idiomas.tr({"en": "Bread"}, "ca"), "")                 # ni castellano
        self.assertEqual(idiomas.tr(None, "en"), "")
        self.assertEqual(idiomas.tr(5, "en"), "")

    def test_c_limpiar_campo(self):
        lc = idiomas.limpiar_campo
        self.assertEqual(lc("  Pan  ", "n", 20), "Pan")                                      # solo castellano: texto
        self.assertEqual(lc({"es": "Pan"}, "n", 20), "Pan")
        self.assertEqual(lc({"es": "Pan", "en": "Bread", "ca": "", "zh": None}, "n", 20), {"es": "Pan", "en": "Bread"})
        self.assertEqual(lc({"es": "Pan", "en": " "}, "n", 20), "Pan")
        self.assertEqual(lc("", "n", 20, vacio=True), "")
        self.assertEqual(lc(None, "n", 20, vacio=True), "")
        with self.assertRaises(ValueError):
            lc("", "n", 20)                                                                  # castellano obligatorio
        with self.assertRaises(ValueError):
            lc({"es": "", "en": "Bread"}, "n", 20, vacio=True)                               # falta castellano
        with self.assertRaises(ValueError):
            lc({"es": "Pan", "nl": "Brood"}, "n", 20)                                         # idioma desconocido
        with self.assertRaises(ValueError):
            lc({"es": "Pan", "en": "x" * 21}, "n", 20)                                       # demasiado largo
        with self.assertRaises(ValueError):
            lc(["Pan"], "n", 20)                                                             # formato no válido
        with self.assertRaises(ValueError):
            lc({"es": 3}, "n", 20)


class FechasYNumeros(unittest.TestCase):
    D = datetime.date(2026, 10, 22)

    def test_d_mes(self):
        esperado = {"es": "octubre de 2026", "en": "October 2026", "ca": "octubre de 2026", "zh": "2026年10月",
                    "fr": "octobre 2026", "de": "Oktober 2026", "it": "ottobre 2026", "pt": "outubro de 2026"}
        for l, v in esperado.items():
            self.assertEqual(idiomas.mes(2026, 10, l), v)
        self.assertEqual(idiomas.mes(2026, 3, "ca"), "març de 2026")

    def test_d_fecha(self):
        esperado = {"es": "22 de octubre de 2026", "en": "22 October 2026", "ca": "22 d’octubre de 2026", "zh": "2026年10月22日",
                    "fr": "22 octobre 2026", "de": "22. Oktober 2026", "it": "22 ottobre 2026", "pt": "22 de outubro de 2026"}
        for l, v in esperado.items():
            self.assertEqual(idiomas.fecha(self.D, l), v)
        self.assertEqual(idiomas.fecha(datetime.date(2026, 3, 1), "ca"), "1 de març de 2026")
        self.assertEqual(idiomas.fecha(datetime.date(2026, 4, 1), "ca"), "1 d’abril de 2026")

    def test_d_dia_semana(self):   # el 22-oct-2026 es jueves
        esperado = {"es": "jueves", "en": "Thursday", "ca": "dijous", "zh": "星期四", "fr": "jeudi", "de": "Donnerstag", "it": "giovedì", "pt": "quinta-feira"}
        for l, v in esperado.items():
            self.assertEqual(idiomas.dia_semana(self.D, l), v)

    def test_d_numero_y_moneda(self):
        self.assertEqual(idiomas.numero(1234.5, "es"), "1.234,50")
        self.assertEqual(idiomas.numero(1234.5, "ca"), "1.234,50")
        self.assertEqual(idiomas.numero(1234.5, "en"), "1,234.50")
        self.assertEqual(idiomas.numero(1234.5, "zh"), "1,234.50")
        self.assertEqual(idiomas.numero(1234.5, "de"), "1.234,50")
        self.assertEqual(idiomas.numero(1234.5, "it"), "1.234,50")
        self.assertEqual(idiomas.numero(1234.5, "fr"), "1\u202f234,50")
        self.assertEqual(idiomas.numero(1234.5, "pt"), "1\u00a0234,50")
        self.assertEqual(idiomas.numero(-3, "es", 0), "-3")
        self.assertEqual(idiomas.moneda(5.5, "es"), "5,50 €")
        self.assertEqual(idiomas.moneda(5.5, "ca"), "5,50 €")
        self.assertEqual(idiomas.moneda(5.5, "en"), "€5.50")
        self.assertEqual(idiomas.moneda(5.5, "zh"), "€5.50")
        for l in ("fr", "de", "it", "pt"):
            self.assertEqual(idiomas.moneda(5.5, l), "5,50 €")
        self.assertEqual(idiomas.moneda(1234.5), "1.234,50 €")

    def test_d_hora(self):
        self.assertEqual(idiomas.hora(datetime.datetime(2026, 10, 22, 9, 5)), "09:05")


class AcceptLanguage(unittest.TestCase):
    def test_e_desde_cabecera(self):
        casos = {
            "zh-CN,zh;q=0.9": "zh",
            "en-US,en;q=0.8": "en",
            "ca": "ca",
            "fr-FR": "fr",
            "de-DE,de;q=0.9": "de",
            "it-IT": "it",
            "pt-PT,pt;q=0.9": "pt",
            "pt-BR": "pt",
            "nl-NL": "es",
            "nl-NL,nl;q=0.9": "es",
            "nl-NL,nl;q=0.9,en;q=0.5": "en",
            "en;q=0.5,ca;q=0.9": "ca",
            "en;q=0": "es",
            "zh;q=0,ca;q=0.2": "ca",
            "ES-es": "es",
            "": "es",
            None: "es",
            "q=0.5;;,": "es",
        }
        for cab, esperado in casos.items():
            self.assertEqual(idiomas.desde_cabecera(cab), esperado, f"Accept-Language {cab!r}")

    def test_e_de_peticion(self):
        self.assertEqual(idiomas.de_peticion({"X-Idioma": "ca", "Accept-Language": "zh"}), "ca")   # manda lo elegido
        self.assertEqual(idiomas.de_peticion({"X-Idioma": "xx", "Accept-Language": "zh"}), "zh")
        self.assertEqual(idiomas.de_peticion({}), "es")


class DatosDeLaDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = os.path.join(RAIZ, "restaurantes", "demo")
        with open(os.path.join(cls.dir, "datos.json"), encoding="utf-8") as f:
            cls.datos = json.load(f)

    def rellenos(self, valor, donde):
        self.assertIsInstance(valor, dict, f"{donde}: debería llevar los ocho idiomas")
        self.assertEqual(set(valor), set(LENGUAS), f"{donde}: idiomas {sorted(valor)}")
        for l in LENGUAS:
            self.assertTrue(isinstance(valor[l], str) and valor[l].strip(), f"{donde}: falta el idioma {l}")

    def test_f_datos_json(self):
        for p in self.datos["platos"]:
            for c in ("n", "d", "sec"):
                self.rellenos(p.get(c), f"plato {p['id']}.{c}")
        for p in self.datos["picar"]:
            self.rellenos(p.get("n"), f"ración {p['id']}.n")
        for k, i in self.datos["ingredientes"].items():
            self.rellenos(i.get("n"), f"ingrediente {k}.n")

    def test_f_datos_js_coherente_con_datos_json(self):
        with open(os.path.join(self.dir, "datos.js"), encoding="utf-8") as f:
            js = f.read()
        m = re.fullmatch(r"window\.DATOS = (.*);\s*", js, re.S)
        self.assertIsNotNone(m, "datos.js no tiene el formato «window.DATOS = …;»")
        self.assertEqual(json.loads(m.group(1)), self.datos, "datos.js no coincide con datos.json")

    def test_f_marca(self):
        m = restaurante.marca()
        for c in ("lema", "intro", "descripcion", "aviso_pie"):
            self.rellenos(m.get(c), f"marca.{c}")
        for c in ("plato", "platos"):
            self.rellenos(m["textos"].get(c), f"marca.textos.{c}")

    def test_f_pasa_la_validacion_del_servidor(self):
        import servidor
        limpio = servidor.validar(json.loads(json.dumps(self.datos)))
        for p in limpio["platos"]:
            self.rellenos(p["n"], f"validado: plato {p['id']}.n")

    def test_f_cae_a_castellano_si_falta_un_idioma(self):
        n = dict(self.datos["platos"][0]["n"])
        n["zh"] = ""
        self.assertEqual(idiomas.tr(n, "zh"), n["es"])


class ClavesDelCodigo(unittest.TestCase):
    """Todas las claves literales que usa el código existen en es.json. Las dinámicas (con prefijo + variable) se ignoran."""
    LITERAL = r"""(['"])([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)\1"""
    PATRONES = [
        re.compile(r"\bI18N\.(?:t|th|tn)\(\s*" + LITERAL + r"\s*[,)]"),
        re.compile(r"\bidiomas\.(?:t|Msg)\(\s*" + LITERAL + r"\s*[,)]"),
        re.compile(r"\b(?:Msg|mensaje_t|_t|tt)\(\s*" + LITERAL + r"\s*[,)]"),
        re.compile(r"""\bdata-i18n(?:-html)?=(['"])([a-z][a-z0-9_.]*)\1"""),
        re.compile(r"\bt\(\s*" + LITERAL + r"\s*,\s*(?:idioma|lang|self\.idioma|l)\b"),
    ]
    ATRIBUTOS = re.compile(r"""\bdata-i18n-attr=(['"])(.*?)\1""")

    def claves_usadas(self):
        usadas = {}
        for ruta in sorted(glob.glob(os.path.join(CARTA, "*.html")) + glob.glob(os.path.join(CARTA, "*.py"))):
            with open(ruta, encoding="utf-8") as f:
                texto = f.read()
            nombre = os.path.basename(ruta)
            for pat in self.PATRONES:
                for m in pat.finditer(texto):
                    usadas.setdefault(m.group(2), set()).add(nombre)
            for m in self.ATRIBUTOS.finditer(texto):
                for par in m.group(2).split(";"):
                    if ":" in par:
                        usadas.setdefault(par.split(":", 1)[1].strip(), set()).add(nombre)
        return usadas

    def test_g_existen_en_es_json(self):
        es = cargar("es")
        faltan = []
        for clave, ficheros in sorted(self.claves_usadas().items()):
            if clave.endswith("."):
                continue   # prefijo de una clave dinámica
            if clave in es or (clave + ".uno" in es and clave + ".otros" in es):
                continue
            faltan.append(f"{clave}  ({', '.join(sorted(ficheros))})")
        self.assertFalse(faltan, f"{len(faltan)} claves que usa el código y no están en es.json:\n  " + "\n  ".join(faltan))


if __name__ == "__main__":
    unittest.main()
