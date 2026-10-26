# SPDX-License-Identifier: EUPL-1.2
"""Los papeles legales (docs/legal/) deben coincidir con el código:  python -m unittest tests.test_papeles   (desde la raíz del repo)
Comprueba que el texto y la versión de la casilla del documento son los de `carta/clientes.py`."""
import os, re, sys, tempfile, shutil, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="papeles-")
os.environ["CARTA_RESTAURANTES"] = TMP
os.environ["RESTAURANTE"] = "demo"
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import clientes  # noqa: E402

LEGAL = os.path.join(RAIZ, "docs", "legal")


def leer(nombre):
    with open(os.path.join(LEGAL, nombre), encoding="utf-8") as f:
        return f.read()


class Papeles(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_texto_de_la_casilla_igual_al_codigo(self):
        doc = leer("texto-casilla.md")
        m = re.search(r"<!-- TEXTO-CASILLA:INICIO -->\n(.+?)\n<!-- TEXTO-CASILLA:FIN -->", doc, re.S)
        self.assertTrue(m, "falta el bloque del texto en texto-casilla.md")
        self.assertEqual(m.group(1).strip().replace("{nombre}", "Bar Demo"), clientes.texto_permiso())

    def test_version_vigente_igual_al_codigo(self):
        doc = leer("texto-casilla.md")
        self.assertIn(f"## Versión vigente: {clientes.TEXTO_VERSION}\n", doc)
        self.assertIn(f"| **{clientes.TEXTO_VERSION}** |", doc)

    def test_canales_cubiertos_documentados(self):
        doc = leer("texto-casilla.md")
        self.assertEqual(clientes.CUBRE, {"email": {"1", "2"}, "wallet": {"2"}})
        self.assertIn("correo** (versiones 1 y 2)", doc)
        self.assertIn("solo versión 2", doc)


if __name__ == "__main__":
    unittest.main()
