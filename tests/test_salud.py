# SPDX-License-Identifier: EUPL-1.2
"""`/salud` informa de la versión desplegada (GIT_SHA):  python -m unittest tests.test_salud -v
Usa una carpeta temporal (CARTA_RESTAURANTES): no toca restaurantes/."""
import json, os, shutil, sys, tempfile, threading, unittest, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="salud-")
os.environ.update(CARTA_RESTAURANTES=TMP, RESTAURANTE="demo")
sys.path.insert(0, os.path.join(RAIZ, "carta"))
import nuevo_restaurante  # noqa: E402

nuevo_restaurante.crear("demo", "Bar Demo", raiz=TMP)
import servidor  # noqa: E402


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Salud(unittest.TestCase):
    def setUp(self):
        self.anterior = os.environ.pop("GIT_SHA", None)

    def tearDown(self):
        os.environ.pop("GIT_SHA", None)
        if self.anterior is not None:
            os.environ["GIT_SHA"] = self.anterior

    def test_version_es_el_git_sha(self):
        os.environ["GIT_SHA"] = "abc1234"
        self.assertEqual(servidor.salud()["version"], "abc1234")

    def test_sin_git_sha_la_version_es_cadena_vacia(self):
        self.assertEqual(servidor.salud()["version"], "")

    def test_por_http_devuelve_json_con_version(self):
        os.environ["GIT_SHA"] = "def5678"
        srv = servidor.Servidor(("127.0.0.1", 0), servidor.Manejador)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/salud", timeout=10) as r:
                self.assertEqual(r.status, 200)
                j = json.loads(r.read())
        finally:
            srv.shutdown()
        self.assertTrue(j["ok"])
        self.assertEqual(j["version"], "def5678")


if __name__ == "__main__":
    unittest.main()
